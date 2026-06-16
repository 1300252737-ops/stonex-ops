"""worker_schedules: list worker schedule configurations."""

from __future__ import annotations

import json
from typing import Any, Optional

from stonex_ops.executor import execute
from stonex_ops.whitelist import WorkerScheduleList


async def run(
    stonx_bin: str,
    env: str,
    path: str,
    tenant: Optional[str] = None,
) -> dict[str, Any]:
    output = await execute(stonx_bin, env, path, WorkerScheduleList(tenant=tenant))
    parsed = json.loads(output)
    return {
        "schedules": parsed.get("schedules", []),
        "tenant": tenant,
    }
