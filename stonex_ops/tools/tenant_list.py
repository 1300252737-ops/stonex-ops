"""tenant_list: list all tenants with identity, status, and connection-state summary."""

from __future__ import annotations

import json
from typing import Any

from stonex_ops.executor import execute
from stonex_ops.whitelist import TenantList


async def run(stonx_bin: str, env: str, path: str) -> dict[str, Any]:
    output = await execute(stonx_bin, env, path, TenantList())
    parsed = json.loads(output)
    return {"tenants": parsed.get("tenants", [])}
