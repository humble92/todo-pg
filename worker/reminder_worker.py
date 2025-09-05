import os
import asyncio
import json
import contextlib
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import asyncpg
import httpx
from dotenv import load_dotenv


# -----------------------------
# Configuration
# -----------------------------
load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_API_BASE = os.getenv("SLACK_API_BASE", "https://slack.com/api")

# Worker knobs
MAX_BATCH = int(os.getenv("REMINDER_WORKER_BATCH", "10"))
VISIBILITY_TIMEOUT_SECS = int(os.getenv("REMINDER_VISIBILITY_TIMEOUT_SECS", "300"))  # 5 minutes
MAX_RETRIES = int(os.getenv("REMINDER_MAX_RETRIES", "5"))
BACKOFF_BASE_SECS = int(os.getenv("REMINDER_BACKOFF_BASE_SECS", "60"))  # 1 minute
BACKOFF_MAX_SECS = int(os.getenv("REMINDER_BACKOFF_MAX_SECS", "3600"))  # 1 hour cap
POLL_INTERVAL_SECS = float(os.getenv("REMINDER_POLL_INTERVAL_SECS", "5"))
POLL_INTERVAL_MIN_SECS = float(os.getenv("REMINDER_POLL_INTERVAL_MIN_SECS", "5"))  # minimum polling interval
POLL_INTERVAL_MAX_SECS = float(os.getenv("REMINDER_POLL_INTERVAL_MAX_SECS", "43200"))  # 3600 * 12 (12 hours), maximum polling interval
POOL_MIN_SIZE = int(os.getenv("REMINDER_POOL_MIN_SIZE", "1"))
POOL_MAX_SIZE = int(os.getenv("REMINDER_POOL_MAX_SIZE", "3"))
POOL_MAX_INACTIVE_LIFETIME = int(os.getenv("REMINDER_POOL_MAX_INACTIVE_LIFETIME", "60"))


def _seconds_backoff(retry_count: int) -> int:
    # Exponential backoff: base * 2^retry_count with a cap
    secs = BACKOFF_BASE_SECS * (2 ** retry_count)
    return min(secs, BACKOFF_MAX_SECS)


async def create_pool() -> asyncpg.Pool:
    async def _init_connection(conn: asyncpg.Connection) -> None:
        await conn.execute("SET search_path TO todo_app, public")
    return await asyncpg.create_pool(
        DATABASE_URL,
        init=_init_connection,
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
        max_inactive_connection_lifetime=POOL_MAX_INACTIVE_LIFETIME,
    )


async def claim_jobs(pool: asyncpg.Pool, limit: int) -> List[asyncpg.Record]:
    query = """
    WITH cte AS (
        SELECT id
        FROM scheduled_reminders
        WHERE status = 'pending'
          AND scheduled_for <= now()
          AND (visibility_timeout IS NULL OR visibility_timeout <= now())
        ORDER BY scheduled_for ASC
        FOR UPDATE SKIP LOCKED
        LIMIT $1
    )
    UPDATE scheduled_reminders s
    SET status = 'processing',
        started_at = now(),
        visibility_timeout = now() + make_interval(secs => $2)
    FROM cte
    WHERE s.id = cte.id
    RETURNING s.id, s.todo_id, s.user_id;
    """
    async with pool.acquire() as conn:
        await conn.execute("SET search_path TO todo_app, public")
        rows = await conn.fetch(query, limit, VISIBILITY_TIMEOUT_SECS)
    return rows


async def fetch_job_details(pool: asyncpg.Pool, reminder_id: int) -> Optional[Dict[str, Any]]:
    query = """
    SELECT s.id AS reminder_id,
           t.id AS todo_id,
           t.description,
           t.due_date,
           t.payload,
           u.id AS user_id,
           u.slack_channel
    FROM scheduled_reminders s
    JOIN todos t ON t.id = s.todo_id
    JOIN users u ON u.id = s.user_id
    WHERE s.id = $1
    """
    async with pool.acquire() as conn:
        await conn.execute("SET search_path TO todo_app, public")
        rec = await conn.fetchrow(query, reminder_id)
    if rec is None:
        return None
    payload = rec["payload"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = None
    return {
        "reminder_id": rec["reminder_id"],
        "todo_id": rec["todo_id"],
        "description": rec["description"],
        "due_date": rec["due_date"],
        "payload": payload,
        "user_id": rec["user_id"],
        "slack_channel": rec["slack_channel"],
    }


async def mark_sent(pool: asyncpg.Pool, reminder_id: int) -> None:
    query = """
    UPDATE scheduled_reminders
    SET status = 'sent', posted_at = now(), visibility_timeout = NULL, error = NULL
    WHERE id = $1
    """
    async with pool.acquire() as conn:
        await conn.execute("SET search_path TO todo_app, public")
        await conn.execute(query, reminder_id)


async def requeue_with_backoff(pool: asyncpg.Pool, reminder_id: int, current_retry: int, error_msg: str) -> None:
    next_retry = current_retry + 1
    if next_retry >= MAX_RETRIES:
        query = """
        UPDATE scheduled_reminders
        SET status = 'failed',
            retry_count = retry_count + 1,
            visibility_timeout = NULL,
            posted_at = NULL,
            error = left($2, 512)
        WHERE id = $1
        """
        async with pool.acquire() as conn:
            await conn.execute("SET search_path TO todo_app, public")
            await conn.execute(query, reminder_id, error_msg)
        return

    delay_secs = _seconds_backoff(next_retry)
    query = """
    UPDATE scheduled_reminders
    SET status = 'pending',
        retry_count = retry_count + 1,
        visibility_timeout = NULL,
        scheduled_for = now() + make_interval(secs => $2),
        started_at = NULL,
        error = left($3, 512)
    WHERE id = $1
    """
    async with pool.acquire() as conn:
        await conn.execute("SET search_path TO todo_app, public")
        await conn.execute(query, reminder_id, delay_secs, error_msg)


async def get_retry_count(pool: asyncpg.Pool, reminder_id: int) -> int:
    async with pool.acquire() as conn:
        await conn.execute("SET search_path TO todo_app, public")
        val = await conn.fetchval("SELECT retry_count FROM scheduled_reminders WHERE id = $1", reminder_id)
        return int(val or 0)


async def post_to_slack(channel: str, text: str) -> None:
    if not SLACK_BOT_TOKEN:
        raise RuntimeError("SLACK_BOT_TOKEN is not configured")
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {"channel": channel, "text": text}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{SLACK_API_BASE}/chat.postMessage", headers=headers, json=payload)
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data}")


def _format_message(job: Dict[str, Any]) -> str:
    due = job["due_date"]
    if isinstance(due, datetime):
        due_text = due.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    else:
        due_text = str(due)
    lines = [
        f"📌 Todo Reminder",
        f"• Description: {job['description']}",
        f"• Due: {due_text}",
    ]
    payload = job.get("payload") or {}
    tags = payload.get("tags") if isinstance(payload, dict) else None
    priority = payload.get("priority") if isinstance(payload, dict) else None
    notes = payload.get("notes") if isinstance(payload, dict) else None
    if tags:
        lines.append(f"• Tags: {', '.join(tags)}")
    if priority:
        lines.append(f"• Priority: {priority}")
    if notes:
        lines.append(f"• Notes: {notes}")
    return "\n".join(lines)


async def process_batch(pool: asyncpg.Pool) -> int:
    claimed = await claim_jobs(pool, MAX_BATCH)
    if not claimed:
        return 0

    for row in claimed:
        reminder_id = row["id"]
        try:
            details = await fetch_job_details(pool, reminder_id)
            if not details:
                # Nothing to send; mark failed to avoid spinning
                await requeue_with_backoff(pool, reminder_id, await get_retry_count(pool, reminder_id), "Missing job details")
                continue
            channel = details["slack_channel"]
            if not channel:
                await requeue_with_backoff(pool, reminder_id, await get_retry_count(pool, reminder_id), "Missing slack_channel")
                continue

            text = _format_message(details)
            await post_to_slack(channel, text)
            await mark_sent(pool, reminder_id)
        except Exception as exc:  # robust handling
            try:
                current_retry = await get_retry_count(pool, reminder_id)
                await requeue_with_backoff(pool, reminder_id, current_retry, str(exc))
            except Exception:
                # As a last resort: swallow to keep worker alive
                pass
    return len(claimed)


async def listen_notifications(pool: asyncpg.Pool, wake_event: asyncio.Event) -> None:
    # Dedicated connection for LISTEN/NOTIFY
    conn: asyncpg.Connection
    async with pool.acquire() as conn:
        await conn.execute("SET search_path TO todo_app, public")
        def _cb(*_):
            print("NOTIFY reminder_pending received")
            wake_event.set()
        await conn.add_listener("reminder_pending", _cb)
        try:
            # Keep this connection parked for notifications
            while True:
                await asyncio.sleep(3600)
        finally:
            await conn.remove_listener("reminder_pending", _cb)


async def main() -> None:
    # Wait for DB to be reachable to avoid crash-loop on startup
    async def _create_pool_with_retry() -> asyncpg.Pool:
        delay = 1
        while True:
            try:
                return await create_pool()
            except Exception as exc:
                print(f"DB connect failed: {exc}. Retrying in {delay}s", flush=True)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    pool = await _create_pool_with_retry()
    wake_event = asyncio.Event()

    # Start listener task
    listener_task = asyncio.create_task(listen_notifications(pool, wake_event))
    print("Reminder worker started. Waiting for jobs…")

    # Adaptive polling variables
    current_poll_interval = POLL_INTERVAL_SECS
    consecutive_empty_batches = 0
    max_consecutive_empty = 2  # After 2 consecutive empty batches, increase interval

    try:
        while True:
            # Process immediately if notified; otherwise poll periodically
            try:
                await asyncio.wait_for(wake_event.wait(), timeout=current_poll_interval)
                wake_event.clear()
                # When event occurs, reset poll interval to minimum
                consecutive_empty_batches = 0
                current_poll_interval = POLL_INTERVAL_MIN_SECS
                print("Event received, resetting poll interval to minimum")
            except asyncio.TimeoutError:
                pass

            processed = await process_batch(pool)
            
            # Adaptive polling interval adjustment
            if processed == 0:
                consecutive_empty_batches += 1
                # The more consecutive empty batches, the greater the poll interval
                if consecutive_empty_batches >= max_consecutive_empty:
                    new_interval = min(
                        current_poll_interval * 1.5, 
                        POLL_INTERVAL_MAX_SECS
                    )
                    if new_interval != current_poll_interval:
                        current_poll_interval = new_interval
                        print(f"Empty batches: {consecutive_empty_batches}, "
                              f"increasing poll interval to {current_poll_interval:.1f}s")
            else:
                # reset poll interval to minimum when jobs are processed
                consecutive_empty_batches = 0
                current_poll_interval = POLL_INTERVAL_MIN_SECS
                print(f"Processed {processed} jobs, resetting poll interval to {current_poll_interval}s")
            
            # If we processed a full batch, loop again immediately to drain
            if processed >= MAX_BATCH:
                continue
    finally:
        listener_task.cancel()
        with contextlib.suppress(Exception):
            await listener_task
        await pool.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Worker stopped by user")
