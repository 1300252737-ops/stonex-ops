"""tenant_show: show a tenant's detailed onboarding and connection state.

The stonx JSON contract flattens `TenantShowScopeOutput` via `#[serde(flatten)]`,
so `shop`, `shop_scope_error`, and `fallback_xhs_auth_path` are all top-level fields.
"""

from __future__ import annotations

import json
from typing import Any

from stonex_ops.executor import execute
from stonex_ops.whitelist import TenantShow


async def run(stonx_bin: str, env: str, path: str, tenant: str) -> dict[str, Any]:
    output = await execute(stonx_bin, env, path, TenantShow(tenant=tenant))
    parsed = json.loads(output)
    return {
        "tenant": parsed.get("tenant", tenant),
        "ops_tag": parsed.get("ops_tag"),
        "status": parsed.get("status"),
        "display_name": parsed.get("display_name"),
        "tenant_business_timezone": parsed.get("tenant_business_timezone"),
        "home_path": parsed.get("home_path"),
        "shop": parsed.get("shop"),
        "shop_scope_error": parsed.get("shop_scope_error"),
        "fallback_xhs_auth_path": parsed.get("fallback_xhs_auth_path"),
        "connections": parsed.get("connections", []),
    }
