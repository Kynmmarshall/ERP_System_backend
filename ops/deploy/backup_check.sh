#!/usr/bin/env bash
# Confirms a recent, real backup and a current WAL archive exist before
# allowing a production migration/deploy to proceed. Per plan.md:
# "confirm successful backup and WAL archive" is a hard gate, not an
# assumption.
#
# NOTE (honest disclosure - see docs/backup-recovery.md): production
# backup automation (pgBackRest, scheduled) has not been installed yet
# in this project. This script checks for the underlying filesystem
# evidence (a base backup + archived WAL segments) that any PITR-capable
# backup tool - pgBackRest or the plain-tools drill in
# ops/backups/pitr_drill.ps1 - must produce. Until pgBackRest is
# deployed on the VPS and pointed at BACKUP_DIR/WAL_ARCHIVE_DIR, this
# gate will correctly and deliberately fail closed rather than pretend
# to pass.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:?BACKUP_DIR must be set (path to latest base backup repository)}"
WAL_ARCHIVE_DIR="${WAL_ARCHIVE_DIR:?WAL_ARCHIVE_DIR must be set (path to archived WAL segments)}"
MAX_BACKUP_AGE_HOURS="${MAX_BACKUP_AGE_HOURS:-24}"
MAX_WAL_AGE_MINUTES="${MAX_WAL_AGE_MINUTES:-15}"

echo "=== Backup gate: base backup freshness ==="
if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
  echo "FAIL: no backup found at $BACKUP_DIR - refusing to migrate/deploy without a restorable backup" >&2
  exit 1
fi
newest_backup=$(find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -n1 | cut -d' ' -f2-)
backup_age_seconds=$(( $(date +%s) - $(date -r "$newest_backup" +%s) ))
backup_age_hours=$(( backup_age_seconds / 3600 ))
if [ "$backup_age_hours" -gt "$MAX_BACKUP_AGE_HOURS" ]; then
  echo "FAIL: newest backup ($newest_backup) is ${backup_age_hours}h old, exceeds ${MAX_BACKUP_AGE_HOURS}h limit" >&2
  exit 1
fi
echo "OK: newest backup is ${backup_age_hours}h old ($newest_backup)"

echo "=== Backup gate: WAL archive freshness (RPO bound) ==="
if [ ! -d "$WAL_ARCHIVE_DIR" ] || [ -z "$(ls -A "$WAL_ARCHIVE_DIR" 2>/dev/null)" ]; then
  echo "FAIL: no archived WAL segments found at $WAL_ARCHIVE_DIR" >&2
  exit 1
fi
newest_wal=$(find "$WAL_ARCHIVE_DIR" -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -n1 | cut -d' ' -f2-)
wal_age_seconds=$(( $(date +%s) - $(date -r "$newest_wal" +%s) ))
wal_age_minutes=$(( wal_age_seconds / 60 ))
if [ "$wal_age_minutes" -gt "$MAX_WAL_AGE_MINUTES" ]; then
  echo "FAIL: newest archived WAL segment is ${wal_age_minutes}m old, exceeds ${MAX_WAL_AGE_MINUTES}m RPO bound" >&2
  echo "Check archive_command/archive_timeout on the production Postgres instance." >&2
  exit 1
fi
echo "OK: newest archived WAL segment is ${wal_age_minutes}m old ($newest_wal)"

echo "Backup gate passed."
