# ICT University ERP — Backend

Microservices backend for the ICT University ERP (Academic, Finance & Marketing,
Administration & HR), built for SEN4121 (Large System Environment).

## Architecture

- `services/identity` — authentication, tenancy, roles, sessions (FastAPI).
- `services/academic` — programs, courses, enrollment, grades, exams (FastAPI).
- `services/finance` — invoicing, payments, campaigns, reporting (FastAPI).
- `services/hr` — recruitment, payroll, attendance, leave, assets (FastAPI).
- `gateway` — Nginx: routing, rate limiting, auth delegation (Phase 2), fronts
  the frontend's built static assets and every service's `/api/v1/*` path.
- `contracts` — versioned JSON Schemas for RabbitMQ events shared between
  services (no shared runtime code).
- `ops` — Postgres bootstrap, backups, deployment and monitoring scripts used
  locally and by Jenkins.

Each service owns its own database (`identity_db`, `academic_db`, `finance_db`,
`hr_db`) inside one shared PostgreSQL instance, with a least-privilege role
that cannot connect to any other service's database — see
`ops/postgres/init/01-init-databases.sh` and
`tests/integration/test_db_isolation.py`.

## Prerequisites

- Docker Desktop / Docker Engine with Compose v2
- The sibling frontend repository checked out at `../ERP_System` relative to
  this repo (the gateway builds and serves it as a container)
- Python 3.13 and Node.js (only needed for running tests/lint outside Docker)

## Quick start (local, full stack)

```powershell
cp .env.example .env   # adjust values if needed; safe dev-only defaults are provided
docker compose up --build
```

Then open http://localhost:8081/healthz (gateway liveness) and
http://localhost:8081/api/v1/academic/healthz (a real request proxied through
the gateway to the academic service).

## Running a single service's checks

```powershell
cd services/identity
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements-dev.txt
ruff check .
mypy app
pytest --cov=app --cov-fail-under=70
```

## Database isolation check

```powershell
cp .env.example .env
docker compose -p erp-ci -f docker-compose.yml -f docker-compose.test.yml up -d --build postgres
pip install -r tests/integration/requirements.txt
pytest tests/integration/test_db_isolation.py
docker compose -p erp-ci -f docker-compose.yml -f docker-compose.test.yml down -v
```

## Status

Phase 1 (foundation): service skeletons, gateway, Compose stack, contracts and
CI checks. Authentication, tenancy, business logic and the Jenkins deployment
pipeline land in later phases — see `docs/` (added progressively) for the full
plan, SRS and architecture record.