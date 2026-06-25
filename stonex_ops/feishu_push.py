"""Push Feishu card alerts when probe finds broken connections."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from stonex_ops.feishu_card import build_connection_alert

FEISHU_OPEN = "https://open.feishu.cn"


def should_push(connections: list[dict[str, Any]]) -> bool:
    """Return True if at least one connection has a real problem."""
    return any(
        c.get("status") != "ok" and not _is_unconfigured(c)
        for c in connections
    )


def _is_unconfigured(c: dict[str, Any]) -> bool:
    """A connection that was never set up is not a real failure."""
    status = c.get("status", "")
    reason = c.get("reason_code", "")
    if status == "config_error":
        return True
    if reason and "missing" in reason.lower():
        return True
    return False


async def push_alert(
    tenant: str,
    tenant_name: str,
    connections: list[dict[str, Any]],
    manage_base_url: str = "https://stonex.yuece.tech",
) -> str | None:
    """Push a connection alert card to the configured Feishu user.

    Reads FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_USER_OPEN_ID from env.
    Returns the message_id on success, or None if credentials are missing.
    """
    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    user_open_id = os.getenv("FEISHU_USER_OPEN_ID", "").strip()

    if not app_id or not app_secret or not user_open_id:
        return None

    # 1. Get tenant_access_token
    token = await _get_tenant_access_token(app_id, app_secret)
    if not token:
        return None

    # 2. Filter out unconfigured connections (not real failures)
    active = [c for c in connections if not _is_unconfigured(c)]
    if not active:
        return None

    # 3. Build card
    now = datetime.now(timezone.utc).astimezone().strftime("%m-%d %H:%M")
    problem_count = sum(1 for c in active if c.get("status") != "ok")
    check_count = len(active)

    card_connections = _format_connections(active)
    manage_url = f"{manage_base_url}/t/{tenant}/"

    card = build_connection_alert(
        tenant=tenant,
        tenant_name=tenant_name or tenant,
        probe_time=now,
        connections=card_connections,
        problem_count=problem_count,
        check_count=check_count,
        manage_url=manage_url,
    )

    # 4. Send card to user (open_id)
    async with httpx.AsyncClient() as client:
        content = json.dumps(card, ensure_ascii=False)
        resp = await client.post(
            f"{FEISHU_OPEN}/open-apis/im/v1/messages?receive_id_type=open_id",
            json={
                "receive_id": user_open_id,
                "msg_type": "interactive",
                "content": content,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        result = resp.json()
        if result.get("code") != 0:
            raise RuntimeError(f"Feishu send message failed: {result}")
        return result.get("data", {}).get("message_id")


async def _get_tenant_access_token(app_id: str, app_secret: str) -> str | None:
    """Obtain a tenant_access_token via Feishu auth API."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{FEISHU_OPEN}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu auth failed: {data}")
        return data.get("tenant_access_token")


def _format_connections(
    connections: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Map raw probe connection entries to card-friendly labels."""
    PROVIDER_MAP: dict[str, str] = {
        "xhs-api": "小红书 XHS",
        "xhs-live": "小红书直播",
        "jst": "库存成本 JST",
        "wangdian": "ERP · 旺店通",
        "feishu": "飞书知识库",
    }

    result: list[dict[str, str]] = []
    for c in connections:
        conn_id = c.get("connection_id", "")
        status = c.get("status", "")
        reason = c.get("reason_code", "")
        message = c.get("message", "")
        detail = _detail(status, reason, message, c.get("checked_at", ""))

        result.append(
            {
                "name": PROVIDER_MAP.get(conn_id, conn_id),
                "provider": PROVIDER_MAP.get(conn_id, conn_id),
                "icon": _status_icon(status),
                "status": status,
                "detail": detail,
            }
        )
    return result


def _status_icon(status: str) -> str:
    if status == "ok":
        return "\U0001f7e2"
    if status in ("action_required",):
        return "\U0001f7e1"
    return "\U0001f534"


def _detail(status: str, reason: str, message: str, checked_at: str) -> str:
    if status == "ok":
        ts = checked_at[11:16] if len(checked_at) >= 16 else checked_at
        return f"正常 \xb7 {ts}"
    if reason and message:
        return f"{reason}: {message}"
    return message or reason or "异常"
