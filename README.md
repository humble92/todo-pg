# PostgreSQL: Harnessing Advanced Features with Architectural Simplicity.

Exploring Postgres 17 via demo of Postgres-only Slack Shared Todo App Backend

## In place of Redis/SQS/Kafka

```
+----------------------+          enqueue (INSERT)          +----------------------------------+
|  Producers           |  --------------------------------> |  PostgreSQL                      |
|  (FE API/Batch/etc.) |                                    |  scheduled_reminders table       |
+----------------------+                                    |  - status FSM                    |
         |                                                / |  - (status, scheduled_for) index |
         |  LISTEN/NOTIFY wakeups                        /  |  - visibility_timeout            |
         v                                              /   |  - retry_count                   |
+-------------------+     poll (FOR UPDATE SKIP LOCKED)     |  - NOTIFY/LISTEN                 |
|  Workers (N)      | <------------------------------------ |                                  |
|  (Docker/VM)      | -----> update status=processing       +----------------------------------+
|                   | -----> set visibility_timeout=now()+lease duration
|                   | -----> do work (idempotent side effects)
|                   | -----> ACK (sent) or NACK (failed + retry++)
+-------------------+
         |
         | cleanup (TTL by posted_at)
         v
+-------------------+
|  Cleanup Job      |
+-------------------+
         |
         | metrics/logs (When needed)
         v
+-------------------+
|  Monitoring/Alert |
|  (Grafana/ELK)    |
+-------------------+
```

## In place of Elasticsearch

FTS(Full text search) with 

```
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_todos_payload_fts ON todos USING GIN (to_tsvector('simple', payload::text));
CREATE INDEX idx_todos_description_trgm ON todos USING GIN (description gin_trgm_ops);
```

## Frontend

https://github.com/humble92/todo-react
