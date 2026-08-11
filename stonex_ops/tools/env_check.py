"""env_check: verify stonex-ops can reach the stonx binary.

Returns:
- current environment
- stonx version
- stonx reachable flag
"""

from __future__ import annotations

from typing import Any

from stonex_ops.executor import execute
from stonex_ops.whitelist import StonxVersion


async def run(stonx_bin: str, env: str, path: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "env": env,
        "stonx_version": None,
        "stonx_reachable": False,
    }

    try:
        output = await execute(stonx_bin, env, path, StonxVersion())
        result["stonx_version"] = output.stdout.strip()
        result["stonx_reachable"] = True
    except Exception:
        pass

    return result
