# Security matrix (OWASP Top 10:2021)

Real implementation facts and the tests that exercise them, for this
project's current state. Anything not fully done is listed as pending,
never claimed as passing. See `/memories/repo/erp-backend-notes.md` (agent
memory, not part of this repo) for the underlying verified facts this
document draws on.

## A01:2021 - Broken Access Control
- **Tenant isolation**: every tenant-owned table in every service has
  Postgres Row-Level Security `FORCE`d on, with a `tenant_isolation` policy
  comparing `institution_id` against a `SET LOCAL app.current_institution_id`
  GUC populated from the caller's verified JWT claims
  (`app/core/tenant_context.py` in each service) - never a client-supplied
  header or body field. Runtime DB roles (`identity_app`, `academic_app`,
  `finance_app`, `hr_app`) do not own their tables and have no
  `BYPASSRLS`/superuser rights; migrations run under a separate owner
  credential (`ops/postgres/init`).
- **Role/route authorization**: every FastAPI endpoint that isn't a public
  health check or the login/refresh/logout trio requires a verified JWT
  (`get_current_claims`) and, where relevant, an explicit role allow-list
  (`require_roles(...)` in each service's `deps.py`).
- **Object ownership**: self-service endpoints (a student's own invoices, a
  staff member's own leave/attendance/payslips) filter by the caller's own
  identity, not a client-supplied id - e.g. `app/routers/leave.py`'s
  `_get_own_employee` looks up the `Employee` row by the verified
  `claims["sub"]`, never by a request parameter.
- **No self-approval**: `app/routers/leave.py`'s decision endpoint rejects
  a decider who is also the request's own employee (403).
- **Gateway defense in depth**: `gateway/nginx.conf` zeroes
  `X-Tenant-Id`/`X-User-Id` on every request, then `auth_request.conf`
  overwrites them from identity's own `/internal/verify` response - a
  spoofed client header can never reach an upstream service. Every service
  ALSO independently re-verifies the JWT itself (signature/issuer/
  audience/expiry) rather than trusting the gateway alone.
- **Tests**: RLS cross-tenant denial (`tests/integration/test_db_isolation.py`
  plus per-service tests using two different seeded `tenant_id`s), role
  403 tests in every router test file (e.g.
  `services/finance/tests/test_expenses.py::test_student_cannot_create_expense`,
  `services/hr/tests/test_leave.py::test_admin_cannot_approve_their_own_leave_request`),
  spoofed-header rejection verified live in Phase 2 (gateway ignores a
  client `X-Tenant-Id` and still returns the JWT's real tenant).

## A02:2021 - Cryptographic Failures
- Passwords hashed with Argon2id (`argon2-cffi` `PasswordHasher()` default
  parameters - time_cost/memory_cost/parallelism per that library's
  current OWASP-aligned defaults), never reversible encryption or a fast
  hash.
- Access tokens are short-lived (10 minutes) RS256-signed JWTs, verified
  independently by every service against the shared public key; only
  identity holds the private key. Refresh tokens are opaque, stored only
  as a SHA-256 hash (never the raw token) in `RefreshSession.token_hash`,
  rotate on every use, and revoke their entire family on reuse detection
  (`services/identity/app/routers/auth.py`).
- Refresh cookie is `HttpOnly`, `SameSite`, and `Secure` in production
  (only disabled for local plain-HTTP dev via `REFRESH_COOKIE_SECURE=false`
  in `docker-compose.yml`, never in `docker-compose.prod.yml`).
- QR shift-attendance tokens use a distinct HS256 secret/audience so they
  can never be replayed as real API access tokens (`services/hr/app/core/security.py`).
  Production now fails closed if that secret is left at its dev default
  (`services/hr/app/core/config.py`'s `_reject_insecure_qr_secret_in_production`
  validator, added this phase; see `tests/test_config.py`).
- Money is stored as integer whole-XAF (`BigInteger`), never floating
  point; rate/percentage fields use `Numeric`/`Decimal`, never `float`.
- Gateway now sends baseline hardening headers on every response
  (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: strict-origin-when-cross-origin`, a restrictive
  `Permissions-Policy` (geolocation and microphone fully disabled; `camera`
  narrowed to `self` because the HR shift check-in scanner reads the shift QR
  code via `getUserMedia`), and a same-origin `Content-Security-Policy` with no
  `unsafe-inline`/`unsafe-eval`) - added and verified this phase against a
  real running build (confirmed zero CSP console violations after fixing
  `font-src` to allow the app's self-hosted `data:`-embedded webfonts).
- **Pending**: production TLS termination is the host's existing Nginx,
  outside this repo (per plan.md) - not yet configured/verified since
  `ERP_DOMAIN` is not yet assigned.

## A03:2021 - Injection
- All application data access goes through SQLAlchemy's ORM/Core query
  builder (parameterized), never raw string-interpolated SQL - except one
  narrow, disclosed case: Postgres `SET LOCAL` (used to set the RLS GUCs)
  does not support bind parameters at all, so `app/core/tenant_context.py`
  in every service validates the tenant id with `uuid.UUID(...)` (raises
  on anything that isn't a real UUID) before interpolating it into the SQL
  text, and hardcodes the `'true'`/`'false'` literal for the boolean flag
  - never interpolates a raw, unvalidated string.
- Pydantic request models validate every request body/query param's shape
  and type before it reaches business logic (e.g. `Field(ge=0)` on every
  monetary/quantity field).
- Frontend never uses `dangerouslySetInnerHTML`/`innerHTML` - React's
  default JSX rendering escapes all interpolated content, and the gateway
  CSP's `script-src 'self'` blocks any injected inline script from
  executing even if a reflected-XSS-shaped payload ever reached the DOM.
- **Tests**: `services/*/tests/` exercise every "raw-SQL enum literal"
  spot (see repo memory - Postgres stores enum `.name`, not `.value`) with
  real DB round-trips, not mocks, so a typo there fails a real test
  instead of silently misbehaving in Postgres.

## A04:2021 - Insecure Design
- Payroll: a `PayrollRun` can only move to `approved` if its backing
  `PayrollScheduleVersion.is_verified` is `true` - the seeded example rate
  schedule ships `is_verified=false` on purpose, so approving payroll with
  unverified/guessed statutory numbers is a hard 403, not a warning
  (`services/hr/app/routers/payroll.py`, proven live in Phase 6).
- Payments: exactly one active (`PENDING`/`SUCCEEDED`) payment intent per
  invoice (partial unique index in the finance migration), reconciliation
  runs inside a `FOR UPDATE`-locked transaction shared by both the
  worker's poller and the untrusted public callback endpoint, so a
  callback body is never trusted as settlement authority by itself - it
  only triggers a re-check against the authoritative provider status.
- Assets: stock movements are rejected inside a `FOR UPDATE`-locked
  transaction if they would drive on-hand stock negative
  (`services/hr/app/routers/assets.py`).
- QR attendance: replay/duplicate check-in is enforced by a DB
  `UniqueConstraint(shift_id, employee_id)`, not just an application-level
  check - proven with a live duplicate-check-in attempt returning 409.

## A05:2021 - Security Misconfiguration
- Containers run as a dedicated non-root `app` user in every Python
  service's Dockerfile (`identity`, `academic`, `finance`, `hr`).
- `security_opt: no-new-privileges:true` now applied to every container
  (`docker-compose.yml`'s shared `x-service-defaults` anchor) and
  `cap_drop: [ALL]` applied to the 6 Python app/worker containers (added
  this phase, verified the whole stack still comes up healthy afterwards).
  **Pending/deferred**: `cap_drop`/`read_only` was NOT applied to the
  `gateway`/`frontend` (nginx-based) or `postgres`/`rabbitmq` images in
  this pass - those need per-image capability testing (e.g. nginx as root
  binding port 80) that wasn't done yet; do not claim this is complete.
- No debug mode. Swagger/OpenAPI (`/docs`, `/redoc`, `/openapi.json`) are
  disabled outright when `environment == "production"` in every service's
  `main.py` (added this phase). This is defense in depth: even before this
  change, the gateway never proxies those paths (only the specific
  `/api/v1/{auth,academic,finance,hr}/...` prefixes are forwarded) and
  `docker-compose.prod.yml` never publishes a service's port directly, so
  the schema was not actually reachable externally - this closes the gap
  for a misconfigured/temporary port publish too.
- Secrets are never committed: `.env`, `.venv*`, and `ops/secrets/dev/`
  are all in `.gitignore`; production secrets are separate files supplied
  by the Jenkins deployment pipeline, mounted read-only
  (`docker-compose.prod.yml`).
- Health/readiness endpoints are unauthenticated by design (needed for
  container orchestration) but expose no sensitive data - only
  `{"status": ..., "service": ...}`.

## A06:2021 - Vulnerable and Outdated Components
- Every service pins exact dependency versions in `requirements.txt`
  (no floating `latest`/unpinned ranges); frontend pins exact `package.json`
  versions.
- **Dependency vulnerability scan**: run this phase with `pip-audit`
  (Python) and `npm audit` (frontend) - see "Dependency scan results"
  below for the real findings and fixes applied, not asserted clean
  without running it.

## A07:2021 - Identification and Authentication Failures
- Account lockout after `max_failed_login_attempts` (default 5) failures
  for `lockout_minutes` (default 15), tracked per-account
  (`services/identity/app/routers/auth.py`).
- Generic "Invalid credentials" error on both wrong-password and
  unknown-email to avoid user enumeration.
- Gateway-level login rate limit (5/minute/IP, burst 5) independent of the
  account-level lockout, so distributed guessing across many accounts from
  one IP is also throttled (`gateway/nginx.conf`).
- Refresh-token reuse detection revokes the entire session family
  immediately (see A02).

## A08:2021 - Software and Data Integrity Failures
- CI builds images from a pinned base (`python:3.13-slim`) and installs
  exact pinned dependency versions from `requirements.txt` - no
  install-from-floating-tag in any Dockerfile.
- The Jenkins deployment pipeline (`ops/jenkins/Deploy.Jenkinsfile` - see
  the Jenkins section below) promotes an explicit image digest produced by
  a green CI run, never a floating `latest` tag or an unreviewed branch
  head.

## A09:2021 - Security Logging and Monitoring Failures
- Structured logs via each service's `logging.basicConfig` write to
  stdout/stderr (captured by Docker's logging driver -> host journald in
  production per plan.md) - no raw passwords/tokens/refresh secrets ever
  logged (only hashed values are persisted; plaintext secrets exist only
  in-memory for the duration of the request).
- **Pending**: a dedicated `docs/monitoring.md`/scheduled host-check script
  is added this phase (see `ops/monitoring/health_check.py`) - a
  lightweight, low-resource alternative to a full Prometheus/Grafana stack
  per plan.md's explicit baseline scope decision.

## A10:2021 - Server-Side Request Forgery (SSRF)
- The only outbound service-initiated HTTP calls are to MTN MoMo's
  collection API, and the base URL is chosen from a fixed, hardcoded
  `{"sandbox": ..., "production": ...}` dict keyed by a trusted server-side
  config value (`CAMERPAY_TARGET_ENVIRONMENT`) - never built from any
  user- or request-supplied string (`services/finance/app/payments/mtn_momo.py`).
  No endpoint in this codebase accepts a URL from a client and fetches it.

## Dependency scan results
Real `pip-audit -r requirements.txt -r requirements-dev.txt` run (this
phase) against each of the four services' venvs, and `npm audit` against
the frontend:

- **Before remediation**: all four Python services shared the same 3
  vulnerable packages (28 total advisories): `pyjwt==2.10.1`,
  `pytest==8.3.4`, and the `starlette==0.41.3` pulled in transitively by
  `fastapi==0.115.6`.
- **Fix applied**: bumped `fastapi` to `0.141.1` (which resolves
  `starlette` to `1.6.0`, now pinned explicitly for reproducibility),
  `pyjwt[crypto]` to `2.14.0`, `pytest` to `9.1.1`, `pytest-asyncio` to
  `1.4.0`, and `pytest-cov` to `7.1.0` (the last two bumped together since
  pytest 9.x requires `pytest-asyncio>=1.4.0`/`pytest-cov>=7`) - in all
  four services' `requirements.txt`/`requirements-dev.txt`.
- **After remediation**: `pip-audit` reports "No known vulnerabilities
  found" for all four services. Full backend test suites (16+85+46+41 =
  188 tests), `ruff check`, and `mypy` all still pass unchanged after the
  bump - no breaking changes encountered from the FastAPI/Starlette/pytest
  major-ish version jumps in this codebase's actual usage.
- `npm audit` (frontend): 0 vulnerabilities across 405 dependencies (19
  prod, 384 dev, 53 optional, 21 peer) - no changes needed.


## Triage / known gaps (disclosed, not silently skipped)
- `cap_drop`/`read_only` not yet applied to gateway/frontend/postgres/
  rabbitmq images.
- FastAPI `/docs`/`/redoc`/`/openapi.json` not yet disabled per-environment.
- No WAF/CDN in front of the gateway (single small VPS baseline, per
  plan.md's explicit scope).
- Live MTN sandbox credentials still not provisioned - CamerPay stays on
  the disclosed deterministic `test_double` adapter; no real provider
  penetration/security testing has been done against MTN's actual API.
- Declarative Jenkinsfile linter validation against the real, authorized
  Jenkins instance, and any real VPS deployment rehearsal, are explicitly
  left to the user (no credentials/network path to that infrastructure
  from this development sandbox) - never claimed as passing here.
