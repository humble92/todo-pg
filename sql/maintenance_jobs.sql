-- =================================================================
-- MAINTENANCE JOBS: CLEANUP & REINDEX (pg_cron)
-- =================================================================
-- Prerequisites
-- 1) Server has pg_cron installed and enabled (shared_preload_libraries=pg_cron)
-- 2) In this database: CREATE EXTENSION IF NOT EXISTS pg_cron;
-- 3) The compose passes: -c cron.database_name=slack_todo_db (or your DB)
--
-- Apply this file to your application database.
-- For check: SELECT * FROM cron.job;

SET search_path TO todo_app, public;

-- =================================================================
-- Archive table for scheduled_reminders
-- =================================================================
-- Keep the same columns (defaults only) + archived_at
CREATE TABLE IF NOT EXISTS todo_app.scheduled_reminders_archive (
    LIKE todo_app.scheduled_reminders INCLUDING DEFAULTS,
    archived_at TIMESTAMPTZ DEFAULT now()
);

-- =================================================================
-- Function: cleanup scheduled_reminders
--  - TTL by posted_at: archive and delete sent/failed older than p_ttl_days
--  - Enforce retry cap: if retry_count >= p_max_retry and status in (pending, processing) => failed
-- =================================================================
CREATE OR REPLACE FUNCTION todo_app.cleanup_scheduled_reminders(
    p_ttl_days  INT DEFAULT 30,
    p_max_retry INT DEFAULT 5
) RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_cutoff TIMESTAMPTZ := now() - make_interval(days => p_ttl_days);
BEGIN
    -- 1) Enforce retry cap: flip to failed when exceeding p_max_retry
    UPDATE todo_app.scheduled_reminders
    SET status = 'failed',
        error = COALESCE(NULLIF(error, ''), 'Retry limit exceeded')
    WHERE retry_count >= p_max_retry
      AND status IN ('pending', 'processing');

    -- 2) Archive old sent/failed rows (posted_at older than cutoff)
    WITH to_archive AS (
        SELECT id
        FROM todo_app.scheduled_reminders
        WHERE posted_at IS NOT NULL
          AND status IN ('sent', 'failed')
          AND posted_at < v_cutoff
    )
    INSERT INTO todo_app.scheduled_reminders_archive
    SELECT s.*, now() AS archived_at
    FROM todo_app.scheduled_reminders s
    JOIN to_archive a ON a.id = s.id
    ON CONFLICT DO NOTHING;

    -- 3) Delete those archived rows
    DELETE FROM todo_app.scheduled_reminders s
    USING (
        SELECT id
        FROM todo_app.scheduled_reminders
        WHERE posted_at IS NOT NULL
          AND status IN ('sent', 'failed')
          AND posted_at < v_cutoff
    ) d
    WHERE s.id = d.id;
END;
$$;

-- =================================================================
-- Schedules (pg_cron)
-- =================================================================
-- Daily cleanup at 03:00 (UTC by default)
DO $do$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM cron.job WHERE jobname = 'cleanup_scheduled_reminders'
    ) THEN
        PERFORM cron.schedule(
            'cleanup_scheduled_reminders',
            '0 3 * * *',
            $cron$SELECT todo_app.cleanup_scheduled_reminders(30, 5);$cron$
        );
    END IF;
END
$do$;

-- Daily reindex at 03:30 (REINDEX CONCURRENTLY must be run outside a function)
DO $do$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM cron.job WHERE jobname = 'reindex_scheduled_reminders'
    ) THEN
        PERFORM cron.schedule(
            'reindex_scheduled_reminders',
            '30 3 * * *',
            $cron$REINDEX TABLE CONCURRENTLY todo_app.scheduled_reminders;$cron$
        );
    END IF;
END
$do$;
