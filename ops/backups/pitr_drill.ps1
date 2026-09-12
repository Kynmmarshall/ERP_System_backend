<#
.SYNOPSIS
  Local point-in-time-recovery (PITR) drill: physical base backup + WAL
  archiving + restore to a timestamp strictly between two known test
  writes, into a brand-new isolated data directory/container - never
  touches the real dev stack's postgres_data volume or any other data.

.DESCRIPTION
  Demonstrates the underlying mechanism plain PostgreSQL PITR relies on
  (pg_basebackup + continuous WAL archiving + recovery_target_time).
  Production is planned to use pgBackRest for the same underlying
  mechanism plus scheduling/compression/retention/encryption automation -
  see docs/backup-recovery.md for that disclosed scope split and the
  real measured results of running this script.

.NOTES
  Every container/volume/file this script touches lives under a fresh
  temp directory and two disposable container names (erp-pitr-primary /
  erp-pitr-restored) - safe to run repeatedly, nothing here is shared
  with the main docker-compose stack.
#>

$drillRoot = Join-Path $env:TEMP "erp-pitr-drill-$(Get-Date -Format yyyyMMddHHmmss)"
$dataDir = Join-Path $drillRoot 'pgdata'
$archiveDir = Join-Path $drillRoot 'wal-archive'
$backupDir = Join-Path $drillRoot 'basebackup'
$restoreDir = Join-Path $drillRoot 'pgdata-restored'
New-Item -ItemType Directory -Force -Path $dataDir, $archiveDir, $backupDir, $restoreDir | Out-Null
Write-Output "Drill working directory: $drillRoot"

function Wait-PostgresReady($containerName) {
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        docker exec $containerName pg_isready -U postgres 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 1
    }
    throw "$containerName did not become ready within 60s"
}

docker rm -f erp-pitr-primary erp-pitr-restored 2>$null | Out-Null

Write-Output "`n=== 1. Starting primary with WAL archiving enabled ==="
docker run -d --name erp-pitr-primary `
    -e POSTGRES_PASSWORD=drillpass `
    -v "${dataDir}:/var/lib/postgresql/data" `
    -v "${archiveDir}:/wal-archive" `
    postgres:17-alpine `
    postgres -c wal_level=replica -c archive_mode=on -c "archive_command=cp %p /wal-archive/%f" -c max_wal_senders=3 | Out-Null
Wait-PostgresReady 'erp-pitr-primary'

Write-Output "`n=== 2. Creating drill table (included in the base backup) ==="
docker exec erp-pitr-primary psql -U postgres -c "CREATE TABLE drill (id serial PRIMARY KEY, label text, written_at timestamptz DEFAULT now());" | Out-Null

Write-Output "`n=== 3. Taking the physical base backup ==="
docker exec erp-pitr-primary rm -rf /tmp/basebackup
docker exec erp-pitr-primary pg_basebackup -U postgres -D /tmp/basebackup -Fp -Xs | Out-Null
docker cp erp-pitr-primary:/tmp/basebackup/. $backupDir | Out-Null

Write-Output "`n=== 4. Writing the 'before' row (data that MUST survive the restore) ==="
docker exec erp-pitr-primary psql -U postgres -c "INSERT INTO drill (label) VALUES ('before-snapshot');" | Out-Null
$beforeTime = (docker exec erp-pitr-primary psql -U postgres -tAc "SELECT to_char(now(), 'YYYY-MM-DD HH24:MI:SS.US');").Trim()
docker exec erp-pitr-primary psql -U postgres -c "SELECT pg_switch_wal();" | Out-Null
Start-Sleep -Seconds 3
Write-Output "before-snapshot committed at: $beforeTime"

Write-Output "`n=== 5. Writing the 'after' row (data that must NOT survive the restore) ==="
docker exec erp-pitr-primary psql -U postgres -c "INSERT INTO drill (label) VALUES ('after-snapshot');" | Out-Null
docker exec erp-pitr-primary psql -U postgres -c "SELECT pg_switch_wal();" | Out-Null
Start-Sleep -Seconds 3

$drillStart = Get-Date
Write-Output "`n=== 6. Simulating disaster: stopping/removing the primary ==="
docker rm -f erp-pitr-primary | Out-Null

Write-Output "`n=== 7. Restoring the base backup into a brand-new, isolated data directory ==="
Copy-Item -Path (Join-Path $backupDir '*') -Destination $restoreDir -Recurse -Force
New-Item -ItemType File -Path (Join-Path $restoreDir 'recovery.signal') -Force | Out-Null
Add-Content -Path (Join-Path $restoreDir 'postgresql.auto.conf') -Value "restore_command = 'cp /wal-archive/%f %p'"
Add-Content -Path (Join-Path $restoreDir 'postgresql.auto.conf') -Value "recovery_target_time = '$beforeTime'"
Add-Content -Path (Join-Path $restoreDir 'postgresql.auto.conf') -Value "recovery_target_action = 'promote'"

Write-Output "`n=== 8. Starting the restored instance (recovers to the target time, then promotes) ==="
docker run -d --name erp-pitr-restored `
    -e POSTGRES_PASSWORD=drillpass `
    -e PGDATA=/var/lib/postgresql/data `
    -v "${restoreDir}:/var/lib/postgresql/data" `
    -v "${archiveDir}:/wal-archive:ro" `
    postgres:17-alpine | Out-Null
Wait-PostgresReady 'erp-pitr-restored'

$drillEnd = Get-Date
$rtoSeconds = [math]::Round(($drillEnd - $drillStart).TotalSeconds, 1)

Write-Output "`n=== 9. Verifying restored data (before-snapshot present, after-snapshot absent) ==="
$rows = docker exec erp-pitr-restored psql -U postgres -tAc "SELECT label FROM drill ORDER BY id;"
Write-Output "Rows present after restore:`n$rows"

$rowsArray = $rows -split "`n" | Where-Object { $_.Trim() -ne '' }
$hasBefore = $rowsArray -contains 'before-snapshot'
$hasAfter = $rowsArray -contains 'after-snapshot'

Write-Output "`n=== RESULT ==="
Write-Output "before-snapshot present: $hasBefore (expected: True)"
Write-Output "after-snapshot present:  $hasAfter (expected: False)"
Write-Output "Measured RTO (disaster -> verified restored, this drill): $rtoSeconds seconds"

if ($hasBefore -and -not $hasAfter) {
    Write-Output "`nPITR DRILL PASSED: restored to a real point in time between two known writes."
} else {
    Write-Output "`nPITR DRILL FAILED - see rows above."
}

Write-Output "`n=== Cleanup ==="
docker rm -f erp-pitr-primary erp-pitr-restored *>$null
Write-Output "Containers removed. Drill artifacts kept at: $drillRoot (delete manually when done reviewing)"
