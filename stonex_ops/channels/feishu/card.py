"""Feishu card JSON builder — pure function, no I/O."""

from __future__ import annotations

from typing import Any


def build_alert_card(
    tenant: str,
    tenant_name: str,
    probe_time: str,
    connections: list[dict[str, str]],
    problem_count: int,
    check_count: int,
    manage_url: str,
) -> dict[str, Any]:
    """Build a connection alert card (Feishu schema 2.0)."""
    header = "red" if problem_count > 0 else "turquoise"
    title_text = (
        "\U0001f514 StoneX \xb7 连接告警"
        if problem_count > 0
        else "\U0001f50c StoneX \xb7 连接状态"
    )

    lines: list[str] = []
    for c in connections:
        lines.append(
            f"{c['icon']} **{c['name']}** \xb7 {c['provider']}\n"
            f"<font color='grey'>{c['detail']}</font>"
        )

    return {
        "schema": "2.0",
        "config": {"update_multi": True, "enable_forward": True, "width_mode": "fill"},
        "header": {
            "title": {"tag": "plain_text", "content": title_text},
            "subtitle": {
                "tag": "plain_text",
                "content": (
                    f"{tenant_name} ({tenant}) \xb7 {probe_time}"
                    f" \xb7 {problem_count}/{check_count} 异常"
                ),
            },
            "template": header,
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": [
                {
                    "tag": "markdown",
                    "content": "\n".join(lines),
                    "text_size": "normal",
                    "margin": "0px 0px 8px 0px",
                },
                {"tag": "hr", "margin": "4px 0px 8px 0px"},
                _button_row(manage_url),
            ],
        },
    }


def _button_row(url: str) -> dict[str, Any]:
    return {
        "tag": "column_set",
        "flex_mode": "bisect",
        "background_style": "default",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "\U0001f527 管理连接"},
                        "type": "default",
                        "width": "fill",
                        "behaviors": [{"type": "open_url", "default_url": url}],
                    }
                ],
            },
        ],
    }
