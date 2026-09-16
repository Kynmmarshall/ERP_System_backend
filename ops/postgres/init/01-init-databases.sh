#!/usr/bin/env bash
# Runs once when the postgres data volume is first initialized.
# Creates one least-privilege role + database per service. Because CONNECT is
# revoked from PUBLIC, a role for one service physically cannot open a
# connection to another service's database - this is the database-per-service
# isolation boundary, verified by tests/integration/test_db_isolation.py.
set -euo pipefail

create_service_db() {
  local db_name="$1"
  local role_name="$2"
  local role_password="$3"

  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE ${role_name} LOGIN PASSWORD '${role_password}';
    CREATE DATABASE ${db_name} OWNER ${role_name};
    REVOKE ALL ON DATABASE ${db_name} FROM PUBLIC;
    GRANT CONNECT ON DATABASE ${db_name} TO ${role_name};
EOSQL
}

create_service_db "identity_db" "identity_app" "${IDENTITY_DB_PASSWORD}"
create_service_db "academic_db" "academic_app" "${ACADEMIC_DB_PASSWORD}"
create_service_db "finance_db" "finance_app" "${FINANCE_DB_PASSWORD}"
create_service_db "hr_db" "hr_app" "${HR_DB_PASSWORD}"
