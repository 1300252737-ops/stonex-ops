"""Entry point: CLI parsing and MCP server bootstrap."""

import argparse
import asyncio
import os
import sys

from stonex_ops.server import run_mcp_server


def _expand_tilde(raw: str) -> str:
    if raw == "~":
        return os.environ.get("HOME", ".")
    if raw.startswith("~/"):
        return os.path.join(os.environ.get("HOME", "."), raw[2:])
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="stonex-ops",
        description="StoneX ops diagnostic tools",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    mcp = sub.add_parser("mcp", help="Start MCP server (stdio JSON-RPC)")
    mcp.add_argument(
        "--stonx-bin",
        default=os.environ.get("STONEX_BIN", "stonx"),
        help="Path to the stonx binary (default: stonx, env: STONEX_BIN)",
    )
    mcp.add_argument(
        "--path",
        default=os.environ.get("STONEX_PATH", "~/.stonex"),
        help="StoneX configuration root (default: ~/.stonex, env: STONEX_PATH)",
    )
    mcp.add_argument(
        "--env",
        dest="env",
        default=os.environ.get("STONEX_ENV", "test"),
        choices=["main", "test", "scratch"],
        help="StoneX environment (default: test, env: STONEX_ENV)",
    )
    mcp.add_argument(
        "--audit-file",
        default=os.environ.get("STONEX_OPS_AUDIT_FILE", None),
        help="Audit log file path (env: STONEX_OPS_AUDIT_FILE)",
    )

    args = parser.parse_args()
    path = _expand_tilde(args.path)

    if args.command == "mcp":
        print(
            f"stonex-ops mcp starting: stonx_bin={args.stonx_bin} "
            f"env={args.env} path={path}",
            file=sys.stderr,
        )
        asyncio.run(
            run_mcp_server(
                stonx_bin=args.stonx_bin,
                env=args.env,
                path=path,
                audit_file=args.audit_file,
            )
        )
