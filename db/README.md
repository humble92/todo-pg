# PostgreSQL

## Database Setup

## NOTE. Known Issue

Change the password in `postgres-init-configmap.yaml`

```base
CREATE USER slack_todo_user WITH PASSWORD 'SHOULD_BE_REPLACED_WITH_DB_PASSWORD';
```

### Database Initialization Order

#### Option 1: Using Docker Compose (Recommended)

1. **Start the database**:
```bash
docker-compose up db -d
```

2. **Wait for database to be ready**:
```bash
docker-compose logs db
# Wait for "database system is ready to accept connections"
```

3. **Initialize database and schema**:
```bash
# copy initializing sqls
docker compose cp sql/init-db.sql db:/tmp/init-db.sql
docker compose cp sql/schema.sql db:/tmp/schema.sql
docker compose cp sql/maintenance_jobs.sql db:/tmp/maintenance_jobs.sql
docker compose cp sql/reminder_insert_cron_jobs.sql db:/tmp/reminder_insert_cron_jobs.sql
```

```bash
# Method 1. then, execute; OR
docker compose exec db psql -U postgres -d postgres -f /tmp/init-db.sql
docker compose exec db psql -U postgres -d slack_todo_db -f /tmp/schema.sql
docker compose exec db psql -U postgres -d slack_todo_db -f /tmp/maintenance_jobs.sql
docker compose exec db psql -U postgres -d slack_todo_db -f /tmp/reminder_insert_cron_jobs.sql
```

```bash
# Method 2. Connect to PostgreSQL container
docker-compose exec db psql -U postgres -d postgres

# Run initialization scripts in order:
\i /tmp/init-db.sql
\i /tmp/schema.sql
\i /tmp/maintenance_jobs.sql
\i /tmp/reminder_insert_cron_jobs.sql
```

#### Option 2: Manual Setup
```bash
# Connect to PostgreSQL
docker-compose exec db psql -U postgres -d postgres
```

1. **Create database and user**:

Run the initialization command in sql/init-db.sql line by line

2. **Create schema and tables**:
```bash
# Connect to the new database
\c slack_todo_db
```
Run the schema script in sql/schema.sql

3. **Set up maintenance jobs**:
Run maintenance jobs script in sql/maintenance_jobs.sql

4. **Set up reminder cron jobs**:
Run reminder cron jobs script in sql/reminder_insert_cron_jobs.sql

### Verification

Check if everything is set up correctly:

```sql
-- Connect to the database
\c slack_todo_db

-- Check if schema exists
\dn

-- Check if tables exist
\dt todo_app.*

-- Check if extensions are installed
SELECT * FROM pg_extension WHERE extname IN ('pgcrypto', 'pg_trgm', 'pg_cron');

-- Check if user has proper permissions
\du slack_todo_user
```

### Troubleshooting

#### Schema already exists
If schema is already created:
```sql
-- Check current schema
SELECT current_schema();

-- Switch to todo_app schema
SET search_path TO todo_app, public;
```

#### Reset everything
To start fresh:
```bash
# Stop and remove containers and volumes
docker-compose down -v

# Start again
docker-compose up db -d
# Then follow the initialization steps above
```
