"""MCP server: stdio JSON-RPC server built on the `mcp` SDK.

Key differences from stonex-mcp:
- No dependency on stonex source.
- Active probes call `stonx ctl probe`; read-only analysis uses PostgreSQL
  through the `stonex_ops_readonly` role.
- Command allowlist + input validation + audit log + output redaction.

Probe boundary: only `ops_probe_connections` triggers `stonx ctl probe`,
which may write `ops.connection_probe_state` through stonx. All other tools
are strictly read-only.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
    ToolAnnotations,
)

from stonex_ops import tools
from stonex_ops.audit import AuditEntry, AuditLogger, AuditStatus
from stonex_ops.db import DEFAULT_MAX_ROWS, MAX_MAX_ROWS, resolve_readonly_database_url
from stonex_ops.executor import ExecutionError, execute
from stonex_ops.redaction import redact
from stonex_ops.whitelist import StonxVersion

# Maximum concurrent tool calls.
MAX_CONCURRENT_CALLS = 3


_RO_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

_PROBE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)

TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="ops_env_check",
        description=(
            "Verify stonex-ops can reach the stonx binary. "
            "Returns the stonx version and environment info. "
            "Does NOT run a probe."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        annotations=_RO_ANNOTATIONS,
    ),
    Tool(
        name="ops_db_schema",
        description=(
            "Inspect the PostgreSQL schema visible to stonex_ops_readonly. "
            "Use this before writing SQL when table or column names are unknown."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "schema": {
                    "type": "string",
                    "description": "Optional PostgreSQL schema name, e.g. ops or dim.",
                },
                "table": {
                    "type": "string",
                    "description": "Optional table name. May be schema-qualified.",
                },
            },
            "additionalProperties": False,
        },
        annotations=_RO_ANNOTATIONS,
    ),
    Tool(
        name="ops_sql_readonly",
        description=(
            "Execute caller-provided PostgreSQL SQL through the stonex_ops_readonly "
            "role. SQL is not templated or parsed by stonex-ops; the database role, "
            "statement_timeout, client timeout, and output redaction are the safety boundary."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "SQL to execute.",
                },
                "max_rows": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_MAX_ROWS,
                    "description": (
                        f"Maximum rows returned per result set (default {DEFAULT_MAX_ROWS})."
                    ),
                },
            },
            "required": ["sql"],
            "additionalProperties": False,
        },
        annotations=_RO_ANNOTATIONS,
    ),
    Tool(
        name="ops_probe_connections",
        description=(
            "Run connection probes for a tenant (or all tenants): "
            "provider, freshness, report readiness, AI model ping, "
            "and mail transport checks. "
            "This is the ONLY tool that triggers `stonx ctl probe`, "
            "which may write `ops.connection_probe_state` through stonx."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "tenant": {
                    "type": "string",
                    "description": "Optional: tenant identity. Omit to probe all active tenants.",
                },
                "shop_id": {
                    "type": "string",
                    "description": "Optional: shop id. Omit to probe all active shops.",
                },
            },
            "additionalProperties": False,
        },
        annotations=_PROBE_ANNOTATIONS,
    ),
]


# ---- Server state ----

class ServerState:
    """State held by the MCP server."""

    def __init__(
        self,
        stonx_bin: str,
        env: str,
        path: str,
        readonly_database_url: Optional[str],
        logger: AuditLogger,
    ) -> None:
        self.stonx_bin = stonx_bin
        self.env = env
        self.path = path
        self.readonly_database_url = readonly_database_url
        self.logger = logger
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)


# ---- Argument validation ----

def _require_string(args: dict[str, Any], key: str) -> str:
    """Extract and validate a required string argument."""
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid argument: {key} must be a non-empty string")
    return value.strip()


def _optional_string(args: dict[str, Any], key: str) -> Optional[str]:
    """Extract an optional string argument; validates the type if present."""
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid argument: {key} must be a string")
    return value.strip()


def _optional_int(args: dict[str, Any], key: str) -> Optional[int]:
    """Extract an optional integer argument; validates the type if present."""
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ValueError(f"invalid argument: {key} must be an integer")


def _max_rows(args: dict[str, Any]) -> int:
    value = _optional_int(args, "max_rows")
    if value is None:
        return DEFAULT_MAX_ROWS
    if value < 1 or value > MAX_MAX_ROWS:
        raise ValueError(f"invalid argument: max_rows must be between 1 and {MAX_MAX_ROWS}")
    return value


def _readonly_database_url(state: ServerState) -> str:
    if not state.readonly_database_url:
        raise ValueError(
            "readonly database URL is unavailable; pass --readonly-database-url "
            "or ensure <path>/<env>/config.toml contains [database].url"
        )
    return state.readonly_database_url


# ---- Tool dispatch ----

async def _execute_tool(
    state: ServerState,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch a tool call to the corresponding implementation."""
    bin_ = state.stonx_bin
    env = state.env
    path = state.path

    if name == "ops_env_check":
        return await tools.env_check(bin_, env, path)

    elif name == "ops_db_schema":
        schema = _optional_string(arguments, "schema")
        table = _optional_string(arguments, "table")
        return await tools.db_schema(_readonly_database_url(state), schema, table)

    elif name == "ops_sql_readonly":
        sql = _require_string(arguments, "sql")
        return await tools.sql_readonly(_readonly_database_url(state), sql, _max_rows(arguments))

    elif name == "ops_probe_connections":
        tenant = _optional_string(arguments, "tenant")
        shop_id = _optional_string(arguments, "shop_id")
        return await tools.probe_connections(bin_, env, path, tenant, shop_id)

    else:
        raise ValueError(f"unknown tool: {name}")


# ---- MCP Server ----

def _create_server(state: ServerState) -> Server:
    """Build the MCP Server with list_tools / call_tool handlers."""

    @asynccontextmanager
    async def _lifespan(server: Server) -> AsyncIterator[ServerState]:
        yield state

    server = Server("stonex-ops", lifespan=_lifespan)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOL_DEFINITIONS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        ctx_state: ServerState = server.request_context.lifespan_context  # type: ignore[union-attr]

        # Concurrency guard
        if ctx_state.semaphore.locked():
            return [TextContent(
                type="text",
                text=json.dumps({
                    "code": "too_many_requests",
                    "message": (
                        f"Too many concurrent requests (max {MAX_CONCURRENT_CALLS}). "
                        "Please retry shortly."
                    ),
                }, ensure_ascii=False),
            )]

        async with ctx_state.semaphore:
            started = time.monotonic()
            error_msg: Optional[str] = None
            status = AuditStatus.success

            try:
                result = await _execute_tool(ctx_state, name, arguments)
                redact(result)
                return [TextContent(
                    type="text",
                    text=json.dumps(result, ensure_ascii=False),
                )]
            except ValueError as exc:
                error_msg = str(exc)
                status = AuditStatus.execution_failed
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "code": "invalid_params",
                        "message": error_msg,
                    }, ensure_ascii=False),
                )]
            except ExecutionError as exc:
                error_msg = str(exc)
                status = AuditStatus.execution_failed
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "code": "execution_failed",
                        "message": error_msg,
                    }, ensure_ascii=False),
                )]
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                status = AuditStatus.execution_failed
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "code": "execution_failed",
                        "message": error_msg,
                    }, ensure_ascii=False),
                )]
            finally:
                duration_ms = int((time.monotonic() - started) * 1000)
                ctx_state.logger.log(AuditEntry(
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    tool=name,
                    arguments=arguments,
                    result_status=status,
                    error=error_msg,
                    duration_ms=duration_ms,
                    session_id=ctx_state.logger.session_id,
                    operator=ctx_state.logger.operator,
                ))

    return server


# ---- Entry point ----

async def run_mcp_server(
    stonx_bin: str,
    env: str,
    path: str,
    audit_file: Optional[str] = None,
    readonly_database_url: Optional[str] = None,
    readonly_database_url_file: Optional[str] = None,
    operator: Optional[str] = None,
) -> None:
    """Start the MCP server (stdio JSON-RPC)."""
    audit_path = Path(audit_file) if audit_file else None
    logger = AuditLogger(audit_path, operator=operator)

    # Startup check: only verify the stonx binary is reachable.
    # We intentionally do NOT call env_check (which no longer runs probe)
    # and we NEVER run ProbeAll at startup.
    try:
        version_output = await execute(stonx_bin, env, path, StonxVersion())
        print(
            f"startup check: stonx version ok ({version_output.strip()})",
            file=sys.stderr,
        )
    except Exception as exc:
        print(f"startup check warning: {exc}", file=sys.stderr)

    try:
        resolved_readonly_database_url = resolve_readonly_database_url(
            path=path,
            env=env,
            readonly_database_url=readonly_database_url,
            readonly_database_url_file=readonly_database_url_file,
        )
        print("startup check: readonly database URL resolved", file=sys.stderr)
    except Exception as exc:
        resolved_readonly_database_url = None
        print(f"startup check warning: readonly database URL unavailable: {exc}", file=sys.stderr)

    state = ServerState(
        stonx_bin=stonx_bin,
        env=env,
        path=path,
        readonly_database_url=resolved_readonly_database_url,
        logger=logger,
    )

    server = _create_server(state)

    async with stdio_server() as (read, write):
        await server.run(
            read,
            write,
            server.create_initialization_options(),
        )
