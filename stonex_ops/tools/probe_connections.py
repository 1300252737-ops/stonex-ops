"""probe_connections: run connection probes for a tenant (or all tenants).

Supported probe types: xhs-api, jst, wangdian, xhs-live, freshness.

This is the ONLY tool that triggers `stonx ctl probe`, which may write
`ops.connection_probe_state` through stonx.

When probes detect broken connections, a Feishu card alert is pushed to the
configured user (FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_USER_OPEN_ID).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from stonex_ops.executor import execute
from stonex_ops.feishu_push import push_alert, should_push
from stonex_ops.whitelist import Probe, ProbeAll, TenantShow

logger = logging.getLogger(__name__)


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

    # ── Feishu alert push on failures (data source connections only) ──
    data_connections = [c for c in all_connections if _is_data_source(c["connection_id"])]
    if tenant and should_push(data_connections):
        try:
            # Also include Feishu connection status from tenant show
            merged = await _merge_feishu_connection(
                stonx_bin, env, path, tenant, data_connections
            )
            tenant_name = parsed.get("scopes", [{}])[0].get("tenant_tag") or tenant
            await push_alert(tenant, tenant_name, merged)
        except Exception:
            logger.exception("feishu push failed, probe continues")

    return {
        "scope": scope_info,
        "result": parsed.get("result"),
        "check_count": parsed.get("check_count"),
        "problem_count": parsed.get("problem_count"),
        "connections": all_connections,
    }


_DATA_SOURCE_IDS = frozenset({"xhs-api", "xhs-live", "jst", "wangdian", "feishu"})
# Note: jst/wangdian 只有一个会被配置，另一个由 _is_unconfigured 过滤掉


def _is_data_source(conn_id: str) -> bool:
    return conn_id in _DATA_SOURCE_IDS


async def _merge_feishu_connection(
    stonx_bin: str,
    env: str,
    path: str,
    tenant: str,
    probe_conns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pull Feishu connection status from tenant show and merge with probe results."""
    try:
        output = await execute(stonx_bin, env, path, TenantShow(tenant=tenant))
        show = json.loads(output)
        for c in show.get("connections", []):
            if c.get("id") != "feishu":
                continue
            feishu_status = c.get("status", "unknown")
            feishu_message = c.get("message", "")
            probe_conns.append({
                "connection_id": "feishu",
                "tenant": tenant,
                "status": "ok" if feishu_status == "ready" else "action_required",
                "reason_code": feishu_status if feishu_status != "ready" else "",
                "message": feishu_message,
                "checked_at": c.get("last_probe_at", ""),
            })
            break
    except Exception:
        logger.exception("merge feishu connection status failed")

    return probe_conns
