"""worker_jobs: list worker jobs with optional tenant/status/limit filters."""

from __future__ import annotations

import json
from typing import Any, Optional

from stonex_ops.executor import execute
from stonex_ops.whitelist import WorkerJobList

_VALID_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "cancelled"})


async def run(
    stonx_bin: str,
    env: str,
    path: str,
    tenant: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    if status and status not in _VALID_STATUSES:
        raise ValueError(
            f"invalid job status: {status}, "
            "valid: queued, running, succeeded, failed, cancelled"
        )

    output = await execute(
        stonx_bin, env, path,
        WorkerJobList(tenant=tenant, status=status, limit=limit),
    )
    parsed = json.loads(output)
    return {
        "jobs": parsed.get("jobs", []),
        "filters": {
            "tenant": tenant,
            "status": status,
            "limit": limit,
        },
    }
