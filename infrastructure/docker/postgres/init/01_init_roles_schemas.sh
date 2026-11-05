#!/bin/bash
# Runs once, on first start of an empty data volume (postgres image entrypoint).
# The SQL is shared with the native setup (data_engineering/scripts/setup_local_db.py) and reads
# its inputs from the container environment set in docker-compose.yml.
set -euo pipefail

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f /opt/olist/init_roles_schemas.sql

echo "Initialized roles and schemas in database $POSTGRES_DB"
