# Backup and recovery (PITR)

## Scope and honest disclosure
- Production target (per plan.md): pgBackRest for scheduled full/
  incremental backups, continuous WAL archival, encryption, and
  retention, on the VPS.
- What was actually built and run in this session: `ops/backups/pitr_drill.ps1`,
  a real, working point-in-time-recovery drill using plain PostgreSQL
  tools (`pg_basebackup` + `archive_command` WAL archiving +
  `recovery_target_time`) - the same underlying mechanism pgBackRest
  wraps, without its scheduling/compression/encryption/retention
  automation. This was a deliberate scope choice for a development-
  environment drill; pgBackRest itself was not installed/run in this
  session (see "Not yet done" below).
- Everything the drill script touches (two disposable containers
  `erp-pitr-primary`/`erp-pitr-restored`, and a fresh `%TEMP%\erp-pitr-drill-*`
  directory per run) is completely isolated from the real docker-compose
  dev stack's `postgres_data` volume - it never reads or writes real
  project data.

## What the drill actually does
1. Starts an isolated Postgres 17 container with WAL archiving enabled
   (`archive_mode=on`, `archive_command=cp %p /wal-archive/%f`).
2. Creates a `drill` table and takes a real physical base backup
   (`pg_basebackup -Fp -Xs`).
3. Inserts a `before-snapshot` row, records its exact commit timestamp,
   forces a WAL segment switch so it's archived immediately.
4. Inserts an `after-snapshot` row, forces another WAL switch.
5. Stops/removes the primary container (simulated disaster).
6. Copies the base backup into a brand-new, separate data directory,
   drops in a `recovery.signal` file and a `postgresql.auto.conf` with
   `restore_command` pointing at the archived WAL directory and
   `recovery_target_time` set to the `before-snapshot`'s exact timestamp
   (`recovery_target_action = 'promote'`).
7. Starts a brand-new Postgres container against that restored data
   directory - it replays WAL up to (and not past) the target time, then
   promotes to a normal writable primary automatically.
8. Queries the `drill` table and asserts `before-snapshot` is present and
   `after-snapshot` is absent.

## Real measured result (this session, `2026-09-12`)
```
before-snapshot present: True (expected: True)
after-snapshot present:  False (expected: False)
Measured RTO (disaster -> verified restored, this drill): 21.8 seconds

PITR DRILL PASSED: restored to a real point in time between two known writes.
```
- **RTO** (time from simulated disaster to a verified, queryable, promoted
  restore): **21.8 seconds** for this tiny single-table drill on a
  developer laptop. This is far under plan.md's <=60 minute target, but
  is NOT a production RTO estimate - a real database with a much larger
  base backup (network/disk-bound copy time) and more WAL to replay will
  take meaningfully longer; re-measure against a representative-sized
  dataset before quoting a production RTO number.
- **RPO**: bounded by how promptly `archive_command` copies each
  completed WAL segment. This drill forces `pg_switch_wal()` immediately
  after each write specifically to make the demo deterministic and fast -
  it does NOT measure real-world RPO under a live, continuously-writing
  workload (where a WAL segment only archives once it fills or
  `archive_timeout` elapses). Configure `archive_timeout` (e.g. 60s) in
  production so RPO has a concrete upper bound even during low-write
  periods, and re-measure RPO under representative write load before
  quoting the <=5 minute target as met.

## Not yet done (disclosed, not silently skipped)
- pgBackRest itself (compression, encryption, retention policies,
  parallel backup/restore, remote repository support) has not been
  installed, configured, or run anywhere in this project yet.
- No off-host/remote backup repository exists yet - this drill's
  "repository" is a local temp directory on the same machine, which
  plan.md explicitly says is not sufficient before handling real
  records ("off-host repository required before using real records").
- Real service databases (identity/academic/finance/hr, four separate
  logical databases in the one Postgres cluster) were not exercised here
  - only a single throwaway `drill` table in a single-purpose isolated
    cluster. A full drill against the actual multi-database cluster,
    including verifying RabbitMQ/session-revocation reconciliation after
    restore (plan.md's recovery procedure: quiesce workers, isolate stale
    queues, replay outboxes, verify inbox idempotency, rotate/revoke
    identity sessions), has not been performed.
- No monitoring/alerting on WAL archive age/backup freshness has been
  wired up beyond `ops/monitoring/health_check.py`'s existing
  disk/service/queue checks (which do not check backup or WAL archive
  status at all yet).

## Reproducing
```powershell
cd ERP_System_backend
powershell -ExecutionPolicy Bypass -File ops\backups\pitr_drill.ps1
```
