"""Feishu REST client — minimal API surface."""

from __future__ import annotations

import json
from typing import Any

import httpx

FEISHU_OPEN = "https://open.feishu.cn"


async def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    """Obtain a tenant_access_token. Raises RuntimeError on failure."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{FEISHU_OPEN}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu auth failed: {data}")
        return str(data["tenant_access_token"])


async def send_card(
    token: str,
    receive_id_type: str,
    receive_id: str,
    card: dict[str, Any],
) -> str:
    """Send an interactive card. Returns message_id. Raises RuntimeError on failure."""
    async with httpx.AsyncClient() as client:
        content = json.dumps(card, ensure_ascii=False)
        resp = await client.post(
            f"{FEISHU_OPEN}/open-apis/im/v1/messages"
            f"?receive_id_type={receive_id_type}",
            json={
                "receive_id": receive_id,
                "msg_type": "interactive",
                "content": content,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        result = resp.json()
        if result.get("code") != 0:
            raise RuntimeError(f"Feishu send message failed: {result}")
        return str(result["data"]["message_id"])
