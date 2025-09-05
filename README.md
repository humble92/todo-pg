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

## Installation

### Prerequisites

**Environment Variables**: Create a `.env` file in the project root:
```bash
# Database Configuration
POSTGRES_PASSWORD=your-strong-postgres-password
POSTGRES_USER=postgres
POSTGRES_DB=postgres
DB_USER=slack_todo_user
DB_PASSWORD=your-db-user-password
DB_NAME=slack_todo_db

# Slack Configuration
SLACK_BOT_TOKEN=your-slack-bot-token
```

### Method 1. Using Serverside Bakend and Docker Compose

#### 1. Database Setup
For detailed database setup instructions, see [db/README.md](db/README.md).

#### 2. Start Database and worker Services
```bash
# Start database, worker, and adminer
docker compose up -d

# Check service status
docker compose ps

# View logs
docker compose logs -f
```

#### 3. Start Backend Service

```bash
# Create virtual environment
uv venv

# Activate virtual environment
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate     # Windows

# Install dependencies
uv pip install -r requirements.txt

# Run FastAPI with hot reload
uvicorn main:app --reload
```

##### Services:

- **Database**: PostgreSQL with pg_cron extension
- **Worker**: Background reminder processing
- **Adminer**: Database administration UI
- **FastAPI**: REST API Backend

### Using K8s

For detailed setup instructions, see [k8s/README.md](k8s/README.md).

## Frontend

https://github.com/humble92/todo-react
