-- Database rights for the IncoPOS tables (the other users are in 003_roles.sql).
-- The password is NOT here (the repo is public). It is set by hand on each machine.
--   incopos_writer = IncoPOS scripts: read/write rows in incopos.*, read branches

-- 1. Create the user (skip if it already exists)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'incopos_writer') THEN
        CREATE ROLE incopos_writer LOGIN;
    END IF;
END
$$;

-- 2. incopos_writer: rows in incopos tables, read-only on branches
GRANT USAGE ON SCHEMA incopos TO incopos_writer;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA incopos TO incopos_writer;
GRANT SELECT ON branches TO incopos_writer;

-- 3. ai_reader: may read the IncoPOS tables too (it stays read-only)
GRANT USAGE ON SCHEMA incopos TO ai_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA incopos TO ai_reader;

-- 4. Tables we add to incopos later get the same rights automatically
ALTER DEFAULT PRIVILEGES IN SCHEMA incopos GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO incopos_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA incopos GRANT SELECT ON TABLES TO ai_reader;