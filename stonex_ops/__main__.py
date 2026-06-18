"""Entry point: CLI parsing, doctor check, and MCP server bootstrap."""

import argparse
import asyncio
import json
import os
import sys

from stonex_ops.db import bootstrap_readonly_role, database_url_from_config
from stonex_ops.doctor import run_doctor_sync
from stonex_ops.server import run_mcp_server


def _expand_tilde(raw: str) -> str:
    if raw == "~":
        return os.environ.get("HOME", ".")
    if raw.startswith("~/"):
        return os.path.join(os.environ.get("HOME", "."), raw[2:])
    return raw


def _config_args(sub) -> None:
    """Add shared stonx config location arguments to a subparser."""
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


def _shared_args(sub) -> None:
    """Add shared host/config arguments to a subparser."""
    sub.add_argument(
        "--stonx-bin",
        default=os.environ.get("STONEX_BIN", "stonx"),
        help="Path to the stonx binary (default: stonx, env: STONEX_BIN)",
    )
    _config_args(sub)
    sub.add_argument(
        "--audit-file",
        default=os.environ.get("STONEX_OPS_AUDIT_FILE", None),
        help="Audit log file path (env: STONEX_OPS_AUDIT_FILE)",
    )
    sub.add_argument(
        "--readonly-database-url",
        default=os.environ.get("STONEX_OPS_READONLY_DATABASE_URL", None),
        help=(
            "Readonly PostgreSQL URL. Defaults to deriving stonex_ops_readonly "
            "from <path>/<env>/config.toml (env: STONEX_OPS_READONLY_DATABASE_URL)."
        ),
    )
    sub.add_argument(
        "--readonly-database-url-file",
        default=os.environ.get("STONEX_OPS_READONLY_DATABASE_URL_FILE", None),
        help="File containing readonly PostgreSQL URL (env: STONEX_OPS_READONLY_DATABASE_URL_FILE)",
    )
    sub.add_argument(
        "--operator",
        default=os.environ.get("STONEX_OPS_OPERATOR", None),
        help="Operator label written to audit records (env: STONEX_OPS_OPERATOR)",
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

    # ---- bootstrap-readonly-db ----
    bootstrap_parser = sub.add_parser(
        "bootstrap-readonly-db",
        help="Create or repair the PostgreSQL readonly role required by SQL ops tools",
    )
    _config_args(bootstrap_parser)
    bootstrap_parser.add_argument(
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
                readonly_database_url=args.readonly_database_url,
                readonly_database_url_file=args.readonly_database_url_file,
                operator=args.operator,
            )
        )

    elif args.command == "doctor":
        result = run_doctor_sync(
            stonx_bin=args.stonx_bin,
            env=args.env,
            path=path,
            audit_file=args.audit_file,
            readonly_database_url=args.readonly_database_url,
            readonly_database_url_file=args.readonly_database_url_file,
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

    elif args.command == "bootstrap-readonly-db":
        try:
            result = bootstrap_readonly_role(database_url_from_config(path, args.env))
        except Exception as exc:
            if getattr(args, "json_output", False):
                print(json.dumps({
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }, indent=2))
            else:
                print(f"bootstrap-readonly-db failed: {type(exc).__name__}: {exc}")
            sys.exit(1)

        if getattr(args, "json_output", False):
            print(json.dumps({"ok": True, **result}, indent=2))
        else:
            action = "created" if result["created"] else "repaired"
            print(
                f"{action} {result['role']}: "
                f"{result['visible_tables']} tables visible across {len(result['schemas'])} schemas"
            )
        sys.exit(0)


if __name__ == "__main__":
    main()
