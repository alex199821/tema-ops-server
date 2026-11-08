-- Database users with limited rights.
-- Passwords are NOT here (the repo is public). They are set by hand on each machine.
--   ops          = owner, only used for migrations
--   wolt_writer  = Wolt scripts: read/write rows in wolt.*, read branches
--   ai_reader    = AI sandbox: read only, queries stopped after 10 seconds

-- 1. Create the users (skip if they already exist)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'wolt_writer') THEN
        CREATE ROLE wolt_writer LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ai_reader') THEN
        CREATE ROLE ai_reader LOGIN;
    END IF;
END
$$;

-- 2. wolt_writer: rows in wolt tables, read-only on branches
GRANT USAGE ON SCHEMA wolt TO wolt_writer;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA wolt TO wolt_writer;
GRANT SELECT ON branches TO wolt_writer;

-- 3. ai_reader: read everything, change nothing, no long queries
GRANT USAGE ON SCHEMA wolt TO ai_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public, wolt TO ai_reader;
ALTER ROLE ai_reader SET default_transaction_read_only = on;
ALTER ROLE ai_reader SET statement_timeout = '10s';

-- 4. Tables we create later get the same rights automatically
ALTER DEFAULT PRIVILEGES IN SCHEMA wolt GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO wolt_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA wolt GRANT USAGE ON SEQUENCES TO wolt_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public, wolt GRANT SELECT ON TABLES TO ai_reader;