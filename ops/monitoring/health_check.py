#!/usr/bin/env python3
"""Lightweight scheduled health check - a low-resource alternative to a
full Prometheus/Grafana stack (explicitly out of scope for baseline per
plan.md's "Optional Prometheus/Grafana profile for richer local
demonstration" note; a 4 GB VPS also running Jenkins/Postgres/RabbitMQ
cannot spare much headroom for an always-on observability stack).

Intended to run via cron on the VPS, e.g. every 5 minutes:
    */5 * * * * /usr/bin/python3 /opt/erp/ops/monitoring/health_check.py >> /var/log/erp-health.log 2>&1 || \
        mail -s "ERP health check failed" ops@example.com < /var/log/erp-health.log

Uses only the Python standard library - no extra dependencies/venv needed
on the VPS for this script.

Exit code 0 = everything healthy. Exit code 1 = at least one check
failed (suitable for cron's "mail on nonzero exit" behavior, or wiring
into any alerting tool that watches process exit codes).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime

GATEWAY_URL = os.environ.get("HEALTHCHECK_GATEWAY_URL", "http://127.0.0.1:8081")
RABBITMQ_MGMT_URL = os.environ.get("HEALTHCHECK_RABBITMQ_MGMT_URL", "http://127.0.0.1:15672")
RABBITMQ_USER = os.environ.get("RABBITMQ_DEFAULT_USER", "")
RABBITMQ_PASS = os.environ.get("RABBITMQ_DEFAULT_PASS", "")
DISK_PATH = os.environ.get("HEALTHCHECK_DISK_PATH", "/")
DISK_WARN_PERCENT = float(os.environ.get("HEALTHCHECK_DISK_WARN_PERCENT", "85"))
MEM_WARN_PERCENT = float(os.environ.get("HEALTHCHECK_MEM_WARN_PERCENT", "90"))
REQUEST_TIMEOUT_SECONDS = 5

# Queues whose dead-letter counterpart having ANY message indicates a
# poison/malformed event that needs manual investigation - see
# services/academic/app/worker.py and services/finance/app/consumer.py.
DEAD_LETTER_QUEUES = ["finance.enrollment_accepted.dlq"]
BACKLOG_WARN_QUEUES = {"finance.enrollment_accepted": 100}

HEALTHZ_PATHS = [
    "/healthz",
    "/api/v1/auth/healthz",
    "/api/v1/academic/healthz",
    "/api/v1/finance/healthz",
    "/api/v1/hr/healthz",
]


def _get_json(url: str, *, auth: tuple[str, str] | None = None) -> object:
    request = urllib.request.Request(url)
    if auth is not None:
        import base64

        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
        return json.loads(response.read())


def check_service_health() -> list[str]:
    problems = []
    for path in HEALTHZ_PATHS:
        url = f"{GATEWAY_URL}{path}"
        try:
            with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
                if response.status != 200:
                    problems.append(f"{path} returned HTTP {response.status}")
        except (urllib.error.URLError, TimeoutError) as exc:
            problems.append(f"{path} unreachable: {exc}")
    return problems


def check_rabbitmq_queues() -> list[str]:
    if not RABBITMQ_USER or not RABBITMQ_PASS:
        return ["RABBITMQ_DEFAULT_USER/RABBITMQ_DEFAULT_PASS not set - skipped queue depth check"]
    problems = []
    try:
        queues = _get_json(f"{RABBITMQ_MGMT_URL}/api/queues", auth=(RABBITMQ_USER, RABBITMQ_PASS))
    except (urllib.error.URLError, TimeoutError) as exc:
        return [f"RabbitMQ management API unreachable: {exc}"]

    depths = {q["name"]: q.get("messages", 0) for q in queues}
    for dlq_name in DEAD_LETTER_QUEUES:
        if depths.get(dlq_name, 0) > 0:
            problems.append(f"Dead-letter queue {dlq_name} has {depths[dlq_name]} message(s) - needs investigation")
    for queue_name, warn_at in BACKLOG_WARN_QUEUES.items():
        if depths.get(queue_name, 0) > warn_at:
            problems.append(f"Queue {queue_name} backlog is {depths[queue_name]} (warn threshold {warn_at})")
    return problems


def check_disk() -> list[str]:
    try:
        usage = shutil.disk_usage(DISK_PATH)
    except OSError as exc:
        return [f"Could not read disk usage for {DISK_PATH}: {exc}"]
    percent_used = (usage.used / usage.total) * 100
    if percent_used >= DISK_WARN_PERCENT:
        return [f"Disk usage at {DISK_PATH} is {percent_used:.1f}% (warn threshold {DISK_WARN_PERCENT}%)"]
    return []


def check_memory() -> list[str]:
    # Linux-only (/proc/meminfo) - the intended deployment target is the
    # Ubuntu VPS; silently skipped elsewhere (e.g. local Windows dev) since
    # this same script also gets exercised there.
    if not os.path.exists("/proc/meminfo"):
        return []
    values: dict[str, int] = {}
    with open("/proc/meminfo", encoding="ascii") as handle:
        for line in handle:
            key, _, rest = line.partition(":")
            digits = "".join(ch for ch in rest if ch.isdigit())
            if digits:
                values[key] = int(digits)
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", total)
    if total == 0:
        return ["Could not parse /proc/meminfo"]
    percent_used = ((total - available) / total) * 100
    if percent_used >= MEM_WARN_PERCENT:
        return [f"Memory usage is {percent_used:.1f}% (warn threshold {MEM_WARN_PERCENT}%)"]
    return []


def main() -> int:
    timestamp = datetime.now(UTC).isoformat()
    all_problems: list[str] = []
    all_problems += check_service_health()
    all_problems += check_rabbitmq_queues()
    all_problems += check_disk()
    all_problems += check_memory()

    if all_problems:
        print(f"[{timestamp}] UNHEALTHY:")
        for problem in all_problems:
            print(f"  - {problem}")
        return 1

    print(f"[{timestamp}] OK: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
