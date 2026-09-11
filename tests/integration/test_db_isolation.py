"""Verifies the database-per-service boundary at the infrastructure level.

Requires the isolated test stack to be running:
    docker compose -p erp-ci -f docker-compose.yml -f docker-compose.test.yml up -d --build postgres
    pip install -r tests/integration/requirements.txt
    pytest tests/integration/test_db_isolation.py

Each service's own role must be able to connect to its own database, and must
be refused (not merely restricted) when it tries to reach any other
service's database. Postgres enforces this natively once CONNECT is revoked
from PUBLIC (see ops/postgres/init/01-init-databases.sh) - there is no
apselect-based bypass to test for it, so this test targets the raw
connection handshake itself.
"""
from __future__ import annotations

import os

import psycopg
import pytest

HOST = os.environ.get("TEST_POSTGRES_HOST", "127.0.0.1")
PORT = int(os.environ.get("TEST_POSTGRES_PORT", "55432"))
ADMIN_USER = os.environ.get("POSTGRES_USER", "postgres_admin")

SERVICE_CREDENTIALS = {
    "identity": ("identity_app", os.environ.get("IDENTITY_DB_PASSWORD", "identity_dev_password"), "identity_db"),
    "academic": ("academic_app", os.environ.get("ACADEMIC_DB_PASSWORD", "academic_dev_password"), "academic_db"),
    "finance": ("finance_app", os.environ.get("FINANCE_DB_PASSWORD", "finance_dev_password"), "finance_db"),
    "hr": ("hr_app", os.environ.get("HR_DB_PASSWORD", "hr_dev_password"), "hr_db"),
}


def _connect(user: str, password: str, dbname: str) -> psycopg.Connection:
    return psycopg.connect(
        host=HOST, port=PORT, user=user, password=password, dbname=dbname, connect_timeout=5
    )


@pytest.mark.parametrize("service_name", list(SERVICE_CREDENTIALS))
def test_service_role_can_connect_to_its_own_database(service_name: str) -> None:
    user, password, own_db = SERVICE_CREDENTIALS[service_name]
    with _connect(user, password, own_db) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)


@pytest.mark.parametrize("service_name", list(SERVICE_CREDENTIALS))
def test_service_role_cannot_connect_to_other_databases(service_name: str) -> None:
    user, password, own_db = SERVICE_CREDENTIALS[service_name]
    for other_name, (_, _, other_db) in SERVICE_CREDENTIALS.items():
        if other_db == own_db:
            continue
        with pytest.raises(psycopg.OperationalError):
            _connect(user, password, other_db)
