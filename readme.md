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
cd services/identity; python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python ..\..\scripts\generate_dev_jwt_keys.py   # writes ops/secrets/dev/*.pem (gitignored)
cd ..\..
docker compose up --build
```

Then apply identity's migrations and seed dev accounts (one per role):

```powershell
docker compose exec identity python -m alembic upgrade head
docker compose exec identity python -m scripts.seed
```

The seed command prints one dev-only email/password per role (Super Admin,
Admin, Staff, Student) for ICT University, plus a second synthetic
institution used only to prove tenant isolation.

Open http://localhost:8081/healthz (gateway liveness) and
http://localhost:8081/api/v1/academic/healthz (a real request proxied through
the gateway to the academic service). Log in via
`POST http://localhost:8081/api/v1/auth/login` with one of the seeded
accounts to get an access token; `GET /api/v1/academic/me` (and finance/hr)
with that token proves the gateway's `auth_request` and each service's
independent JWT verification both work end-to-end.

## Running a single service's checks

```powershell
cd services/identity
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements-dev.txt
ruff check .
mypy app
$env:JWT_PRIVATE_KEY_PATH = (Resolve-Path ..\..\ops\secrets\dev\jwt_private_key.pem).Path
$env:JWT_PUBLIC_KEY_PATH = (Resolve-Path ..\..\ops\secrets\dev\jwt_public_key.pem).Path
$env:DATABASE_URL = "postgresql+asyncpg://identity_app:identity_dev_password@127.0.0.1:55432/identity_db"  # see below
pytest --cov=app --cov-fail-under=70
```

Identity's test suite needs a real, migrated Postgres reachable at that URL
(its auth/RLS tests are integration tests, not mocked) — bring one up with
the isolated test stack below, then run `alembic upgrade head` against it,
before running identity's `pytest`. academic/finance/hr only need
`JWT_PUBLIC_KEY_PATH` (to verify) and `JWT_PRIVATE_KEY_PATH_FOR_TESTS` (their
tests mint tokens with it) pointed at the same dev keypair.

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
CI checks.

Phase 2 (identity/auth): Argon2 password hashing, RS256 JWT access tokens,
rotating opaque refresh tokens with reuse-family revocation, account
lockout, Postgres row-level-security tenant isolation, a gateway
`auth_request` policy, and independent JWT verification in every service.
Business modules (Academic, Finance & Marketing, HR) and the Jenkins
deployment pipeline land in later phases — see `docs/` (added progressively)
for the full plan, SRS and architecture record.

## Requirements and design documents

The detailed [LaTeX SRS and Software Design Document package](docs/specifications/README.md)
covers this backend and the sibling `ERP_System` frontend, aligned with the
SEN4121 assignment in `docs/`. It includes compiled PDFs, 21 editable PlantUML
diagrams, requirement/test traceability, and an explicit distinction between
implemented behavior, incomplete features and operational targets.