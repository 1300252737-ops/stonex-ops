"""Entry point: CLI parsing, doctor check, and MCP server bootstrap."""

import argparse
import asyncio
import json
import os
import sys

from stonex_ops.doctor import run_doctor_sync
from stonex_ops.server import run_mcp_server


def _expand_tilde(raw: str) -> str:
    if raw == "~":
        return os.environ.get("HOME", ".")
    if raw.startswith("~/"):
        return os.path.join(os.environ.get("HOME", "."), raw[2:])
    return raw


def _shared_args(sub) -> None:
    """Add --stonx-bin, --path, --env, --audit-file to a subparser."""
    sub.add_argument(
        "--stonx-bin",
        default=os.environ.get("STONEX_BIN", "stonx"),
        help="Path to the stonx binary (default: stonx, env: STONEX_BIN)",
    )
    sub.add_argument(
        "--path",
        default=os.environ.get("STONEX_PATH", "~/.stonex"),
        help="StoneX configuration root (default: ~/.stonex, env: STONEX_PATH)",
    )
    sub.add_argument(
        "--env",
        dest="env",
        default=os.environ.get("STONEX_ENV", "test"),
        choices=["main", "test", "scratch"],
        help="StoneX environment (default: test, env: STONEX_ENV)",
    )
    sub.add_argument(
        "--audit-file",
        default=os.environ.get("STONEX_OPS_AUDIT_FILE", None),
        help="Audit log file path (env: STONEX_OPS_AUDIT_FILE)",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="stonex-ops",
        description="StoneX ops diagnostic tools",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- mcp ----
    mcp_parser = sub.add_parser("mcp", help="Start MCP server (stdio JSON-RPC)")
    _shared_args(mcp_parser)

    # ---- doctor ----
    doctor_parser = sub.add_parser(
        "doctor",
        help="Read-only host compatibility check (no probe)",
    )
    _shared_args(doctor_parser)
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output result as JSON",
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

    elif args.command == "doctor":
        result = run_doctor_sync(
            stonx_bin=args.stonx_bin,
            env=args.env,
            path=path,
            audit_file=args.audit_file,
        )

        if getattr(args, "json_output", False):
            print(json.dumps({
                "passed": result.passed,
                "checks": result.checks,
            }, indent=2))
        else:
            for check in result.checks:
                status = "OK" if check["ok"] else "FAIL"
                print(f"  [{status}] {check['check']}: {check['detail']}")

        if not result.passed:
            sys.exit(1)
        sys.exit(0)


if __name__ == "__main__":
    main()
