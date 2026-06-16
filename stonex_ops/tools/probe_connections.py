"""probe_connections: run connection probes for a tenant (or all tenants).

Supported probe types: xhs-api, jst, wangdian, xhs-live, freshness.

This is the ONLY tool that triggers `stonx ctl probe`, which may write
`ops.connection_probe_state` through stonx.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from stonex_ops.executor import execute
from stonex_ops.whitelist import Probe, ProbeAll


async def run(
    stonx_bin: str,
    env: str,
    path: str,
    tenant: Optional[str] = None,
    shop_id: Optional[str] = None,
) -> dict[str, Any]:
    if tenant:
        cmd = Probe(tenant=tenant, shop_id=shop_id)
    else:
        cmd = ProbeAll()

    output = await execute(stonx_bin, env, path, cmd)
    parsed = json.loads(output)

    # Collect connections from all scopes, injecting tenant/shop_id context.
    all_connections: list[dict[str, Any]] = []
    for scope in parsed.get("scopes", []):
        for conn in scope.get("connections", []):
            entry = dict(conn)
            if "tenant" in scope:
                entry["tenant"] = scope["tenant"]
            if "shop_id" in scope:
                entry["shop_id"] = scope["shop_id"]
            all_connections.append(entry)

    scope_info = None
    if tenant:
        scope_info = {"tenant": tenant, "shop": shop_id}

    return {
        "scope": scope_info,
        "result": parsed.get("result"),
        "check_count": parsed.get("check_count"),
        "problem_count": parsed.get("problem_count"),
        "connections": all_connections,
    }
