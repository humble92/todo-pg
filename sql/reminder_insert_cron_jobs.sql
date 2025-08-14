-- =================================================================
-- PG_CRON SETUP & DAILY ENQUEUE JOB
-- =================================================================
-- Requirements:
-- 1) The pg_cron extension must be installed and loaded:
--    - shared_preload_libraries must include 'pg_cron'
--    - In Docker Compose, start postgres with: -c shared_preload_libraries=pg_cron
-- 2) Create the extension in the target database (here, run in slack_todo_db):
--    CREATE EXTENSION IF NOT EXISTS pg_cron;
--
-- After enabling pg_cron, run this file against the 'slack_todo_db' database.
-- For manual trigger: 
-- 1) SELECT todo_app.enqueue_due_today();
-- 2) SELECT pg_notify('reminder_pending','manual_trigger');

-- Use the app schema first
SET search_path TO todo_app, public;

-- =================================================================
-- Function: enqueue all todos due today into scheduled_reminders
-- =================================================================
CREATE OR REPLACE FUNCTION todo_app.enqueue_due_today() RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO todo_app.scheduled_reminders (todo_id, user_id, scheduled_for, status)
    SELECT t.id, t.user_id, now(), 'pending'
    FROM todo_app.todos AS t
    WHERE COALESCE(t.completed, false) = false
      AND t.due_date::date = CURRENT_DATE
      AND NOT EXISTS (
          SELECT 1
          FROM todo_app.scheduled_reminders AS s
          WHERE s.todo_id = t.id
      );
END;
$$;

-- =================================================================
-- Schedule: every day at 02:00 (UTC) run the enqueue function
-- =================================================================
-- This uses pg_cron. The job runs in the current database where this command executes.
-- Cron format: minute hour day-of-month month day-of-week
-- "0 2 * * *" = 02:00 every day
DO $do$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM cron.job WHERE jobname = 'enqueue_due_today'
    ) THEN
        PERFORM cron.schedule(
            'enqueue_due_today',
            '0 2 * * *',
            $cron$SELECT todo_app.enqueue_due_today();$cron$
        );
    END IF;
END
$do$;
