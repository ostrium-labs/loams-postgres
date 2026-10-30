-- The compute image smoke for a beta major whose extensions are not all ported
-- yet (NF2 Task 8, LP-0056; built with EXTENSIONS=v<N>): every `core` extension
-- of design §51 §7.1 that the image has is created, the missing ones are listed
-- (a missing core extension blocks the major's promotion, not its beta, §62
-- §4.7), and pg_stat_statements answers. pgvector, PostGIS and wal2json are
-- checked when present. core-extensions.sql is the full check, run for every
-- major built with EXTENSIONS=all. Run by scripts/loams/smoke/run.sh as
-- cloud_admin.
\set ON_ERROR_STOP on

-- Contrib and Neon's extensions come with every image: these must exist.
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS hstore;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS intarray;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
CREATE EXTENSION IF NOT EXISTS tablefunc;
CREATE EXTENSION IF NOT EXISTS cube;
CREATE EXTENSION IF NOT EXISTS earthdistance;
CREATE EXTENSION IF NOT EXISTS postgres_fdw;
CREATE EXTENSION IF NOT EXISTS dblink;
CREATE EXTENSION IF NOT EXISTS pg_buffercache;
CREATE EXTENSION IF NOT EXISTS pg_prewarm;
CREATE EXTENSION IF NOT EXISTS pgstattuple;
CREATE EXTENSION IF NOT EXISTS amcheck;
CREATE EXTENSION IF NOT EXISTS pg_walinspect;
CREATE EXTENSION IF NOT EXISTS neon;
CREATE EXTENSION IF NOT EXISTS neon_utils;

-- Third-party core extensions: created when the image has them.
CREATE SCHEMA IF NOT EXISTS partman;
DO $$
DECLARE
  e text;
  missing text[] := '{}';
BEGIN
  FOREACH e IN ARRAY ARRAY['vector', 'postgis', 'pg_cron', 'pg_partman', 'pgaudit', 'pg_hint_plan',
                           'hypopg', 'pg_repack', 'pg_ivm', 'pg_session_jwt'] LOOP
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = e) THEN
      IF e = 'pg_partman' THEN
        EXECUTE 'CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman';
      ELSE
        EXECUTE format('CREATE EXTENSION IF NOT EXISTS %I', e);
      END IF;
    ELSE
      missing := missing || e;
    END IF;
  END LOOP;
  IF cardinality(missing) > 0 THEN
    RAISE WARNING 'core extensions not built for Postgres % yet: %',
      current_setting('server_version_num')::int / 10000, array_to_string(missing, ', ');
  END IF;
END $$;

DO $$
BEGIN
  IF (SELECT count(*) FROM pg_stat_statements) < 1 THEN
    RAISE EXCEPTION 'pg_stat_statements recorded nothing';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
    CREATE TABLE loams_smoke_items (id int, embedding vector(3));
    INSERT INTO loams_smoke_items VALUES (1, '[1,2,3]'), (2, '[4,5,6]');
    IF (SELECT id FROM loams_smoke_items ORDER BY embedding <-> '[3,1,2]' LIMIT 1) <> 1 THEN
      RAISE EXCEPTION 'pgvector: wrong nearest neighbour';
    END IF;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis') THEN
    IF ST_AsText(ST_Point(1, 2)) <> 'POINT(1 2)' THEN
      RAISE EXCEPTION 'PostGIS: ST_Point(1, 2) is %', ST_AsText(ST_Point(1, 2));
    END IF;
  END IF;
END $$;

-- wal2json is an output plugin, not an extension: decode one change with it when
-- the image has it (creating the slot fails with undefined_file without it).
CREATE TABLE loams_smoke_wal (id int PRIMARY KEY);
DO $$
BEGIN
  BEGIN
    PERFORM pg_create_logical_replication_slot('loams_smoke', 'wal2json');
  EXCEPTION WHEN undefined_file THEN
    RAISE WARNING 'wal2json is not built for this major yet';
    RETURN;
  END;
END $$;
INSERT INTO loams_smoke_wal VALUES (1);
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_replication_slots WHERE slot_name = 'loams_smoke') THEN
    IF (SELECT count(*) FROM pg_logical_slot_get_changes('loams_smoke', NULL, NULL)
        WHERE data LIKE '%loams_smoke_wal%') <> 1 THEN
      RAISE EXCEPTION 'wal2json did not decode the insert';
    END IF;
    PERFORM pg_drop_replication_slot('loams_smoke');
  END IF;
END $$;
SELECT extname, extversion FROM pg_extension ORDER BY extname;
