-- =================================================================
-- DROP ALL CREATED OBJECTS
-- =================================================================
-- This script drops all objects created by schema.sql in reverse order
-- Set the search path to todo_app schema
SET search_path TO todo_app;
-- =================================================================
-- DROP TABLES (this will automatically drop related indexes)
-- =================================================================
-- Drop scheduled_reminders table first (due to foreign key constraints)
DROP TABLE IF EXISTS scheduled_reminders CASCADE;
-- Drop todos table
DROP TABLE IF EXISTS todos CASCADE;
-- Drop users table
DROP TABLE IF EXISTS users CASCADE;
-- =================================================================
-- DROP CUSTOM TYPES
-- =================================================================
-- Drop the custom ENUM type
DROP TYPE IF EXISTS reminder_status CASCADE;
-- =================================================================
-- DROP SCHEMA
-- =================================================================
-- Drop the entire schema (this will drop all remaining objects)
DROP SCHEMA IF EXISTS todo_app CASCADE;
-- =================================================================
-- RESET SEARCH PATH
-- =================================================================
-- Reset search path to default
SET search_path TO DEFAULT;
-- =================================================================
-- NOTES
-- =================================================================
-- Extensions (pgcrypto, pg_trgm) are not dropped as they might be used by other schemas
-- If you want to drop extensions as well, uncomment the following lines:
-- DROP EXTENSION IF EXISTS pg_trgm CASCADE;
-- DROP EXTENSION IF EXISTS pgcrypto CASCADE;