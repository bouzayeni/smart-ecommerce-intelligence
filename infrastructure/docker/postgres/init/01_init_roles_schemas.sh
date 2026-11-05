#!/bin/bash
# Runs once, on first start of an empty data volume (postgres image entrypoint).
# Creates least-privilege roles and the warehouse schemas.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v db="$POSTGRES_DB" \
    -v etl_user="$ETL_DB_USER" -v etl_password="$ETL_DB_PASSWORD" \
    -v analytics_user="$ANALYTICS_DB_USER" -v analytics_password="$ANALYTICS_DB_PASSWORD" \
    -v app_user="$APP_DB_USER" -v app_password="$APP_DB_PASSWORD" <<'EOSQL'
-- Login roles
CREATE ROLE :"etl_user"       LOGIN PASSWORD :'etl_password';
CREATE ROLE :"analytics_user" LOGIN PASSWORD :'analytics_password';
CREATE ROLE :"app_user"       LOGIN PASSWORD :'app_password';

-- Group role holding read access to curated data only
CREATE ROLE analytics_reader NOLOGIN;
GRANT analytics_reader TO :"analytics_user", :"app_user";

-- Lock down defaults
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO :"etl_user", :"analytics_user", :"app_user";
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Warehouse layers (owned by the ETL role, which also runs dbt and ML batch scoring)
CREATE SCHEMA raw          AUTHORIZATION :"etl_user";  -- bronze: untouched CSV loads + metadata
CREATE SCHEMA staging      AUTHORIZATION :"etl_user";  -- silver: dbt staging models
CREATE SCHEMA intermediate AUTHORIZATION :"etl_user";  -- dbt intermediate models
CREATE SCHEMA marts        AUTHORIZATION :"etl_user";  -- gold: star schema + KPI views
CREATE SCHEMA ml           AUTHORIZATION :"etl_user";  -- model scores, forecasts, anomalies
CREATE SCHEMA app          AUTHORIZATION :"app_user";  -- users, refresh tokens, audit log

-- Readers see marts and ml only (never raw/staging)
GRANT USAGE ON SCHEMA marts, ml TO analytics_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE :"etl_user" IN SCHEMA marts GRANT SELECT ON TABLES TO analytics_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE :"etl_user" IN SCHEMA ml    GRANT SELECT ON TABLES TO analytics_reader;

-- The analytics role (BI + AI assistant) can never write and cannot run long queries
ALTER ROLE :"analytics_user" SET default_transaction_read_only = on;
ALTER ROLE :"analytics_user" SET statement_timeout = '15s';
ALTER ROLE :"app_user"       SET statement_timeout = '30s';
EOSQL

echo "Initialized roles and schemas in database $POSTGRES_DB"
