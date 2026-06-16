"""ops_report_status: show recent report generation status.

Derives daily/weekly report status from the worker job list.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from stonex_ops.executor import execute
from stonex_ops.whitelist import WorkerJobList


async def run(
    stonx_bin: str,
    env: str,
    path: str,
    tenant: Optional[str] = None,
) -> dict[str, Any]:
    output = await execute(
        stonx_bin, env, path,
        WorkerJobList(tenant=tenant, limit=50),
    )
    parsed = json.loads(output)
    jobs: list[dict[str, Any]] = parsed.get("jobs", [])

    summaries: list[dict[str, str]] = []
    for j in jobs:
        attempt_count = j.get("attempt_count")
        if isinstance(attempt_count, (int, float)):
            attempt_count = str(attempt_count)
        else:
            attempt_count = "-"
        summaries.append({
            "job_id": j.get("job_id", "-"),
            "tenant": j.get("tenant", "-"),
            "shop_id": j.get("shop_id", "-"),
            "kind": j.get("kind", "-"),
            "status": j.get("status", "-"),
            "attempt_count": attempt_count,
            "run_after": j.get("run_after", "-"),
        })

    latest_daily = next(
        (s for s in summaries if s["kind"] == "daily" and s["status"] == "succeeded"),
        None,
    )
    latest_weekly = next(
        (s for s in summaries if s["kind"] == "weekly" and s["status"] == "succeeded"),
        None,
    )

    return {
        "tenant": tenant,
        "latest_daily": latest_daily,
        "latest_weekly": latest_weekly,
        "recent_jobs": summaries,
    }
