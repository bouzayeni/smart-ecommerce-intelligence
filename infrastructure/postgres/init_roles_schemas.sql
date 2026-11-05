-- Least-privilege roles and warehouse schemas. Idempotent: safe to re-run; re-running also
-- resyncs role passwords with the environment.
--
-- Run with psql against the target database. All inputs come from environment variables
-- (\getenv, psql 15+), so secrets never appear on a command line:
--   POSTGRES_DB, ETL_DB_USER, ETL_DB_PASSWORD, ANALYTICS_DB_USER, ANALYTICS_DB_PASSWORD,
--   APP_DB_USER, APP_DB_PASSWORD
-- Callers: infrastructure/docker/postgres/init/01_init_roles_schemas.sh (Docker) and
--          data_engineering/scripts/setup_local_db.py (native install).

\set ON_ERROR_STOP on
\getenv db POSTGRES_DB
\getenv etl_user ETL_DB_USER
\getenv etl_password ETL_DB_PASSWORD
\getenv analytics_user ANALYTICS_DB_USER
\getenv analytics_password ANALYTICS_DB_PASSWORD
\getenv app_user APP_DB_USER
\getenv app_password APP_DB_PASSWORD

-- Login roles
SELECT format('CREATE ROLE %I LOGIN', r) FROM unnest(ARRAY[:'etl_user', :'analytics_user', :'app_user']) AS r
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) \gexec
ALTER ROLE :"etl_user"       LOGIN PASSWORD :'etl_password';
ALTER ROLE :"analytics_user" LOGIN PASSWORD :'analytics_password';
ALTER ROLE :"app_user"       LOGIN PASSWORD :'app_password';

-- Group role holding read access to curated data only
SELECT 'CREATE ROLE analytics_reader NOLOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics_reader') \gexec
GRANT analytics_reader TO :"analytics_user", :"app_user";

-- Lock down defaults
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO :"etl_user", :"analytics_user", :"app_user";
-- The warehouse owner may create schemas (dbt custom schemas, isolated test schemas) and
-- temporary tables (bronze COPY staging). REVOKE ALL above removed TEMP from PUBLIC.
GRANT CREATE, TEMPORARY ON DATABASE :"db" TO :"etl_user";
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Warehouse layers (owned by the ETL role, which also runs dbt and ML batch scoring)
CREATE SCHEMA IF NOT EXISTS raw          AUTHORIZATION :"etl_user";  -- bronze: untouched CSV loads + metadata
CREATE SCHEMA IF NOT EXISTS staging      AUTHORIZATION :"etl_user";  -- silver: dbt staging models
CREATE SCHEMA IF NOT EXISTS intermediate AUTHORIZATION :"etl_user";  -- dbt intermediate models
CREATE SCHEMA IF NOT EXISTS marts        AUTHORIZATION :"etl_user";  -- gold: star schema + KPI views
CREATE SCHEMA IF NOT EXISTS ml           AUTHORIZATION :"etl_user";  -- model scores, forecasts, anomalies
CREATE SCHEMA IF NOT EXISTS app          AUTHORIZATION :"app_user";  -- users, refresh tokens, audit log

-- Readers see marts and ml only (never raw/staging)
GRANT USAGE ON SCHEMA marts, ml TO analytics_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA marts, ml TO analytics_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE :"etl_user" IN SCHEMA marts GRANT SELECT ON TABLES TO analytics_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE :"etl_user" IN SCHEMA ml    GRANT SELECT ON TABLES TO analytics_reader;

-- The analytics role (BI + AI assistant) can never write and cannot run long queries
ALTER ROLE :"analytics_user" SET default_transaction_read_only = on;
ALTER ROLE :"analytics_user" SET statement_timeout = '15s';
ALTER ROLE :"app_user"       SET statement_timeout = '30s';
