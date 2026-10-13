-- The compute image smoke (LP-0011, NF1 Task 11; core_extensions_create): every
-- `core` extension of design §51 §7.1 is created (or already is: compute_ctl
-- creates some itself), then pg_stat_statements,
-- pgvector and PostGIS answer a query. Run by scripts/loams/smoke/run.sh as
-- cloud_admin. NF1 Task 20's manifest replaces this list with its `core` tier.
\set ON_ERROR_STOP on

-- Postgres contrib
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

-- Neon's extensions (compatibility names, D822)
CREATE EXTENSION IF NOT EXISTS neon;
CREATE EXTENSION IF NOT EXISTS neon_utils;

-- Third-party core extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE SCHEMA partman;
CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman;
CREATE EXTENSION IF NOT EXISTS pgaudit;
CREATE EXTENSION IF NOT EXISTS pg_hint_plan;
CREATE EXTENSION IF NOT EXISTS hypopg;
CREATE EXTENSION IF NOT EXISTS pg_repack;
CREATE EXTENSION IF NOT EXISTS pg_ivm;
CREATE EXTENSION IF NOT EXISTS pg_session_jwt;

-- wal2json is an output plugin, not an extension: decode one change with it.
CREATE TABLE loams_smoke_wal (id int PRIMARY KEY);
SELECT 'slot' FROM pg_create_logical_replication_slot('loams_smoke', 'wal2json');
INSERT INTO loams_smoke_wal VALUES (1);
SELECT count(*) = 1 AS wal2json_ok
  FROM pg_logical_slot_get_changes('loams_smoke', NULL, NULL) WHERE data LIKE '%loams_smoke_wal%';
SELECT pg_drop_replication_slot('loams_smoke');

-- Queries
SELECT count(*) >= 1 AS pg_stat_statements_ok FROM pg_stat_statements;
CREATE TABLE loams_smoke_items (id int, embedding vector(3));
INSERT INTO loams_smoke_items VALUES (1, '[1,2,3]'), (2, '[4,5,6]');
SELECT id AS nearest FROM loams_smoke_items ORDER BY embedding <-> '[3,1,2]' LIMIT 1;
SELECT ST_AsText(ST_Point(1, 2)) AS postgis_ok;
DO $$
DECLARE
  missing text;
BEGIN
  SELECT string_agg(e, ', ') INTO missing
    FROM unnest(ARRAY['pg_stat_statements', 'pgcrypto', 'uuid-ossp', 'hstore', 'citext', 'pg_trgm',
                      'btree_gin', 'btree_gist', 'ltree', 'intarray', 'unaccent', 'fuzzystrmatch',
                      'tablefunc', 'cube', 'earthdistance', 'postgres_fdw', 'dblink', 'pg_buffercache',
                      'pg_prewarm', 'pgstattuple', 'amcheck', 'pg_walinspect', 'neon', 'neon_utils',
                      'vector', 'postgis', 'pg_cron', 'pg_partman', 'pgaudit', 'pg_hint_plan', 'hypopg',
                      'pg_repack', 'pg_ivm', 'pg_session_jwt']) AS e
   WHERE e NOT IN (SELECT extname FROM pg_extension);
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'core extensions missing: %', missing;
  END IF;
END $$;
SELECT extname, extversion FROM pg_extension ORDER BY extname;
