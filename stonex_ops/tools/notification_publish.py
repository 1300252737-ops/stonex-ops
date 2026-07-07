"""notification_publish: explicitly send a notification via a channel.

Credentials are read from `ops.feishu_connections` when a DB connection is
available, falling back to environment variables (FEISHU_APP_ID,
FEISHU_APP_SECRET, FEISHU_USER_OPEN_ID, FEISHU_CHAT_ID).

Token cache is keyed by app_id for multi-tenant safety.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

from stonex_ops.channels.feishu import build_alert_card, get_tenant_access_token, send_card
from stonex_ops.whitelist import is_safe_identity

_DATA_SOURCE_IDS = frozenset({"xhs-api", "xhs-live", "jst", "wangdian"})

_PROVIDER_MAP: dict[str, str] = {
    "xhs-api": "小红书 XHS",
    "xhs-live": "小红书直播",
    "jst": "库存成本 JST",
    "wangdian": "ERP · 旺店通",
}

# Token cache keyed by app_id.
_token_cache: dict[str, tuple[str, float]] = {}

_DB_CONNECT_TIMEOUT = 5.0


async def _load_credentials(
    readonly_database_url: str | None,
    tenant: str,
) -> dict[str, str]:
    """Load Feishu credentials from `ops.feishu_connections`, falling back to env vars.

    Uses a direct psycopg connection to bypass the SQL executor's output redaction
    (which would redact app_secret because the column name matches the "secret" pattern).
    app_secret is always read from the FEISHU_APP_SECRET env var because stonx encrypts
    it at rest via the crypto key — stonex-ops cannot decrypt it.
    """
    if readonly_database_url and is_safe_identity(tenant):
        try:
            conn = await asyncio.wait_for(
                psycopg.AsyncConnection.connect(readonly_database_url, autocommit=True),
                timeout=_DB_CONNECT_TIMEOUT,
            )
            try:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "SELECT app_id, user_open_id "
                        "FROM ops.feishu_connections "
                        "WHERE tenant_id = %s",
                        (tenant,),
                    )
                    row = await cur.fetchone()
            finally:
                await conn.close()

            if row:
                app_id = (row.get("app_id") or "").strip()
                user_open_id = (row.get("user_open_id") or "").strip()
                # app_secret cannot come from DB — stonx encrypts it at rest.
                app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
                if app_id and app_secret:
                    return {
                        "app_id": app_id,
                        "app_secret": app_secret,
                        "user_open_id": user_open_id,
                    }
        except (psycopg.OperationalError, psycopg.InterfaceError, OSError) as exc:
            print(
                f"stonex-ops: feishu credentials DB lookup failed for "
                f"tenant={tenant}: {exc}",
                file=sys.stderr,
            )

    # Fallback to environment variables.
    return {
        "app_id": os.getenv("FEISHU_APP_ID", "").strip(),
        "app_secret": os.getenv("FEISHU_APP_SECRET", "").strip(),
        "user_open_id": os.getenv("FEISHU_USER_OPEN_ID", "").strip(),
    }


async def run(
    tenant: str,
    tenant_name: str,
    connections: list[dict[str, Any]],
    target: list[str] | None = None,
    manage_base_url: str = "https://stonex.yuece.tech",
    readonly_database_url: str | None = None,
) -> dict[str, Any]:
    """Send connection alert cards via Feishu.

    Returns {"cards": [...]} on success, {"healthy": True} when all data-sources
    are healthy (no alert needed), or {"error": "..."} on failure.
    Callers must check for "cards" (alert sent), "healthy" (skipped), or "error".
    """
    creds = await _load_credentials(readonly_database_url, tenant)
    if not creds["app_id"] or not creds["app_secret"]:
        return {"error": "Feishu channel not configured"}

    targets = _resolve_targets(target, user_open_id=creds["user_open_id"])
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
        return {"healthy": True}

    try:
        token = await _get_token_cached(creds["app_id"], creds["app_secret"])
    except Exception as exc:
        return {"error": f"feishu auth failed: {exc}"}

    now = datetime.now(timezone.utc).astimezone().strftime("%m-%d %H:%M")
    base = manage_base_url or "https://stonex.yuece.tech"
    manage_url = f"{base}/t/{tenant}/connections"

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


def _resolve_targets(
    target: list[str] | None,
    user_open_id: str = "",
) -> list[str]:
    if target:
        return [t.strip() for t in target if t.strip()]
    result: list[str] = []
    for uid in user_open_id.split(","):
        uid = uid.strip()
        if uid:
            result.append(uid)
    # chat_id only comes from env var (not stored in feishu_connections table).
    chat = os.getenv("FEISHU_CHAT_ID", "").strip()
    if chat:
        result.append(chat)
    return result


# ── token cache ──


async def _get_token_cached(app_id: str, app_secret: str) -> str:
    now_ts = datetime.now(timezone.utc).timestamp()
    entry = _token_cache.get(app_id)
    if entry:
        token, ts = entry
        if (now_ts - ts) < 3600:
            return token
    token = await get_tenant_access_token(app_id, app_secret)
    _token_cache[app_id] = (token, now_ts)
    return token


# ── send ──


async def _send_with_retry(
    token: str,
    receive_id_type: str,
    receive_id: str,
    card: dict[str, Any],
) -> str:
    """Send a card with retry on transient network errors only.

    Network errors (timeout, connection refused, DNS failure) are retried up
    to 3 times with a 1-second delay. Non-transient errors (Feishu API
    rejection, malformed card) fail immediately.
    """
    last_err = ""
    for attempt in range(3):
        try:
            return await send_card(token, receive_id_type, receive_id, card)
        except httpx.HTTPError as exc:
            # Transient: network/timeout/DNS — retry.
            last_err = str(exc)
            if attempt < 2:
                await asyncio.sleep(1)
        except Exception as exc:
            # Non-transient: API rejection, malformed payload — do not retry.
            return f"error: {exc}"
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
        return f"OK · {ts}{suffix}"
    if reason and message:
        return f"{reason}: {message}{suffix}"
    return (message or reason or "Error") + suffix
