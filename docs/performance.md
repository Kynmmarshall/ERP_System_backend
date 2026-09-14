# Load test evidence (k6)

## Scope and honest disclosure
- plan.md's target: 25 concurrent sessions for 5 minutes, p95 <500ms for
  ordinary authenticated CRUD reads (excluding external-provider latency),
  error rate <1%.
- This run: `tests/load/k6-smoke.js`, 25 VUs, 90s, against the LOCAL
  docker-compose stack's gateway (`http://localhost:8081`) on the
  developer's Windows machine - NOT the production VPS, NOT a dedicated
  load-test environment. The machine was also running Docker Desktop
  (having just rebuilt 8 images), several browser tabs, and this coding
  session at the same time - i.e. NOT an idle, representative host. Full
  target duration (5 min) was not run in this session; report this
  60-90s smoke result as what it is, not as the full target.
- Reads exercised: `GET /api/v1/academic/programs`, `/api/v1/academic/terms`,
  `/api/v1/finance/expenses`, `/api/v1/hr/positions`, authenticated once
  via a single admin login in `setup()` (shared token, never re-logging in
  per VU/iteration - see the script's comments for why).

## Real bug found in the first attempt: self-inflicted rate-limiting
- First run (no pacing between iterations): 99.56% of requests failed.
  This was NOT a backend bug - the gateway's per-client-IP general rate
  limit (`gateway/nginx.conf`: 20 req/s + burst 40) was doing exactly its
  job against what looked like a single abusive IP, because ALL 25 k6 VUs
  share the one load-generator host's source IP - unlike real production
  traffic spread across many independent users/networks. Added a
  randomized think-time `sleep(10-20s)` per iteration to desynchronize the
  25 VUs; this is a property of testing from one machine, not a finding
  about the gateway (which behaved correctly).

## Final measured results (25 VUs, 90s, after fixing the pacing bug)
- Error rate: 0.48% (3 / 621 requests) - **passes** the <1% target.
- Read latency: avg 187.9ms, median 69.8ms, p90 807ms, **p95 882.9ms** -
  **fails** the <500ms target.
- The median (69.8ms) shows most reads are fast; the p90/p95 tail is
  where the target is missed. Two plausible, NOT yet isolated causes,
  most likely both contributing simultaneously on this loaded dev box:
  1. Host resource contention from this same session's concurrent Docker
     image rebuilds/browser/IDE activity - not present on a dedicated or
     production host.
  2. Every service uses `poolclass=NullPool` for its async SQLAlchemy
     engine (a deliberate fix for a real Windows+asyncpg+pooled-connection
     bug found in Phase 2 - see `/memories/repo/erp-backend-notes.md`),
     meaning each request opens a brand-new Postgres connection with no
     server-side reuse. That trade-off was accepted at prior phases' scale
     and flagged there as "revisit if per-request DB latency ever
     matters" - this load test is the first evidence that it might, under
     concurrency, on constrained hardware.
- **Conclusion**: do not claim the <500ms p95 target is met. Re-measure on
  a dedicated (non-shared) host, ideally close to the eventual VPS's
  specs, for a trustworthy number before using this for a go/no-go
  decision. If it still misses target there, investigate a
  connection-pooling strategy compatible with the platform actually
  deployed to (the Windows+asyncpg NullPool workaround is Windows-dev-only
  context; production is Linux, where the original pooling bug may not
  even apply - worth re-testing pooled engines on Linux specifically).

## How to reproduce
```powershell
k6 run --env BASE_URL=http://localhost:8081 `
  --env ADMIN_PASSWORD=<seeded admin password> `
  --env SMOKE_VUS=25 --env SMOKE_DURATION=90s `
  tests/load/k6-smoke.js
```
 ++                                                                                                                                                                                                                                                                                                                                                                  