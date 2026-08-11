"""probe_connections: run connection probes for a tenant or all tenants.

The stonx CLI owns the probe catalog. stonex-ops intentionally passes through
all returned connection IDs, including provider, freshness, report, AI, and
mail readiness checks.

This is the ONLY tool that triggers `stonx ctl probe`, which may write
`ops.connection_probe_state` through stonx.

Read-only — does not send notifications.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional

from stonex_ops.executor import execute
from stonex_ops.whitelist import Probe, ProbeAll

_EMPTY_RESULT: dict[str, Any] = {
    "scope": None,
    "scopes": [],
    "result": "failed",
    "check_count": 0,
    "problem_count": 0,
    "connections": [],
}


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

    try:
        parsed = json.loads(output.stdout)
    except json.JSONDecodeError:
        print(
            f"stonex-ops: probe returned invalid JSON "
            f"(length={len(output.stdout)}): {output.stdout[:300]!r}",
            file=sys.stderr,
        )
        error = output.stderr.strip() or "stonx probe produced no JSON output"
        return {**_EMPTY_RESULT, "error": error}

    # Collect connections from all scopes, injecting tenant/shop_id context.
    all_connections: list[dict[str, Any]] = []
    for scope in parsed.get("scopes", []):
        for conn in scope.get("connections", []):
            entry = dict(conn)
            if "tenant" in scope:
                entry["tenant"] = scope["tenant"]
            if "shop_id" in scope:
                entry["shop_id"] = scope["shop_id"]
                entry["shop_label"] = scope.get("shop_label", scope["shop_id"])
            all_connections.append(entry)

    scope_info = None
    if tenant:
        scope_info = {"tenant": tenant, "shop": shop_id}

    return {
        "scope": scope_info,
        "scopes": parsed.get("scopes", []),
        "result": parsed.get("result"),
        "check_count": parsed.get("check_count"),
        "problem_count": parsed.get("problem_count"),
        "connections": all_connections,
    }
