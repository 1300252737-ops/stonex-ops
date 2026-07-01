"""MCP stdio smoke test: verify stonex-ops starts and lists tools.

Usage:
    python tests/smoke_mcp.py /path/to/stonex-ops STONX_BIN \\
        [--env E] [--path P] [--audit-file F]
"""

from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _run() -> None:
    stonex_ops_bin = sys.argv[1]
    stonx_bin = sys.argv[2] if len(sys.argv) > 2 else "/bin/echo"
    extra_args = sys.argv[3:]

    params = StdioServerParameters(
        command=stonex_ops_bin,
        args=["mcp", "--stonx-bin", stonx_bin, *extra_args],
    )

    async with stdio_client(params, errlog=sys.stderr) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools_result = await session.list_tools()

    tools = tools_result.tools
    names = [tool.name for tool in tools]
    assert names == [
        "ops_env_check",
        "ops_db_schema",
        "ops_sql_readonly",
        "ops_probe_connections",
        "ops_notification_publish",
    ], f"unexpected tools: {names}"
    assert "ops_env_check" in names, f"missing ops_env_check in {names}"
    assert "ops_probe_connections" in names, "missing ops_probe_connections"

    server_info = getattr(init, "serverInfo", None) or getattr(init, "server_info", None)
    server_name = getattr(server_info, "name", "?")
    print(f"initialize OK: server={server_name}")
    print(f"list_tools OK: {len(names)} tools ({', '.join(names[:3])}...)")


def main() -> None:
    asyncio.run(asyncio.wait_for(_run(), timeout=30))
    print("MCP stdio smoke all checks passed")


if __name__ == "__main__":
    main()
