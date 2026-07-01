"""notification_publish: explicitly send a notification via a channel."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from stonex_ops.channels.feishu import build_alert_card, get_tenant_access_token, send_card

# Feishu credentials read once at process boundary.
_APP_ID = os.getenv("FEISHU_APP_ID", "").strip()
_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "").strip()

_DATA_SOURCE_IDS = frozenset({"xhs-api", "xhs-live", "jst", "wangdian"})

_PROVIDER_MAP: dict[str, str] = {
    "xhs-api": "小红书 XHS",
    "xhs-live": "小红书直播",
    "jst": "库存成本 JST",
    "wangdian": "ERP · 旺店通",
}


def ready() -> bool:
    """Check if the Feishu channel credentials are configured."""
    return bool(_APP_ID and _APP_SECRET)


async def run(
    tenant: str,
    tenant_name: str,
    connections: list[dict[str, Any]],
    target: list[str] | None = None,
    manage_base_url: str = "https://stonex.yuece.tech",
) -> dict[str, Any]:
    """Send connection alert cards via Feishu.

    Args:
        target: List of open_id (ou_) or chat_id (oc_) to send to.
                Defaults to FEISHU_USER_OPEN_ID + FEISHU_CHAT_ID env vars.

    Returns {"cards": [...]} on success, {"error": "..."} on failure.
    """
    if not ready():
        return {"error": "Feishu channel not configured (missing env vars)"}

    targets = _resolve_targets(target)
    if not targets:
        return {"error": "no recipients configured"}

    data = [c for c in connections if c.get("connection_id", "") in _DATA_SOURCE_IDS]
    active = [c for c in data if not _is_unconfigured(c)]
    if not active:
        return {"error": "no active connections to report"}

    shops: dict[str, list[dict[str, Any]]] = {}
    for c in active:
        shop = c.get("shop_label", c.get("shop_id", "unknown"))
        shops.setdefault(shop, []).append(c)

    problem_shops = {
        shop: conns
        for shop, conns in shops.items()
        if any(c.get("status") != "ok" for c in conns)
    }
    if not problem_shops:
        return {"status": "ok", "message": "all connections healthy"}

    try:
        token = await _get_token_cached()
    except Exception as exc:
        return {"error": f"feishu auth failed: {exc}"}

    now = datetime.now(timezone.utc).astimezone().strftime("%m-%d %H:%M")
    base = manage_base_url or "https://stonex.yuece.tech"
    manage_url = f"{base}/t/{tenant}/"

    all_results: list[dict[str, Any]] = []
    for shop, conns in problem_shops.items():
        problem_count = sum(1 for c in conns if c.get("status") != "ok")
        card = build_alert_card(
            tenant=tenant,
            tenant_name=f"{tenant_name} · {shop}",
            probe_time=now,
            connections=_format_connections(conns, problem_only=True),
            problem_count=problem_count,
            check_count=len(conns),
            manage_url=manage_url,
        )
        delivered = {}
        for t in targets:
            id_type = "chat_id" if t.startswith("oc_") else "open_id"
            delivered[t] = await _send_with_retry(token, id_type, t, card)
        all_results.append({"shop": shop, "delivered": delivered})

    return {"cards": all_results}


# ── target resolution ──

def _resolve_targets(target: list[str] | None) -> list[str]:
    if target:
        return [t.strip() for t in target if t.strip()]
    # Backwards-compatible fallback to env vars.
    result: list[str] = []
    for uid in os.getenv("FEISHU_USER_OPEN_ID", "").split(","):
        uid = uid.strip()
        if uid:
            result.append(uid)
    chat = os.getenv("FEISHU_CHAT_ID", "").strip()
    if chat:
        result.append(chat)
    return result


# ── token cache ──

_token: str | None = None
_token_ts: float = 0.0


async def _get_token_cached() -> str:
    global _token, _token_ts
    now_ts = datetime.now(timezone.utc).timestamp()
    if _token and (now_ts - _token_ts) < 3600:
        return _token
    _token = await get_tenant_access_token(_APP_ID, _APP_SECRET)
    _token_ts = now_ts
    return _token


# ── send ──

async def _send_with_retry(
    token: str, receive_id_type: str, receive_id: str, card: dict[str, Any]
) -> str:
    last_err = ""
    for attempt in range(3):
        try:
            return await send_card(token, receive_id_type, receive_id, card)
        except Exception as exc:
            last_err = str(exc)
            if attempt < 2:
                import asyncio
                await asyncio.sleep(1)
    return f"error after 3 attempts: {last_err}"


# ── helpers ──

def _is_unconfigured(c: dict[str, Any]) -> bool:
    status = c.get("status", "")
    reason = c.get("reason_code", "")
    return status == "config_error" or (bool(reason) and "missing" in reason.lower())


def _format_connections(
    connections: list[dict[str, Any]], problem_only: bool = False
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for c in connections:
        conn_id = c.get("connection_id", "")
        status = c.get("status", "")
        if problem_only and status == "ok":
            continue
        reason = c.get("reason_code", "")
        message = c.get("message", "")
        detail = _detail(status, reason, message, c.get("checked_at", ""), c.get("shop_label", ""))
        name = _PROVIDER_MAP.get(conn_id, conn_id)
        result.append({"name": name, "provider": name, "icon": _icon(status), "detail": detail})
    return result


def _icon(status: str) -> str:
    if status == "ok":
        return "\U0001f7e2"
    if status == "action_required":
        return "\U0001f7e1"
    return "\U0001f534"


def _detail(status: str, reason: str, message: str, checked_at: str, shop: str = "") -> str:
    suffix = f" ({shop})" if shop else ""
    if status == "ok":
        ts = checked_at[11:16] if len(checked_at) >= 16 else checked_at
        return f"正常 \xb7 {ts}{suffix}"
    if reason and message:
        return f"{reason}: {message}{suffix}"
    return (message or reason or "异常") + suffix
