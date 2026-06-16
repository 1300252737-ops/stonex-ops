"""MCP server: stdio JSON-RPC server built on the `mcp` SDK.

Key differences from stonex-mcp:
- No DB connection, no dependency on stonex source.
- Tools call `stonx ctl ... --output json` exclusively.
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
from pathlib import Path
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
    ToolAnnotations,
)

from stonex_ops import tools
from stonex_ops.audit import AuditEntry, AuditLogger, AuditStatus
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
        name="ops_tenant_list",
        description=(
            "List all tenants with identity, status, and connection-state summary."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        annotations=_RO_ANNOTATIONS,
    ),
    Tool(
        name="ops_tenant_show",
        description=(
            "Show a single tenant's detailed onboarding state: "
            "identity, ops tag, status, shop scope, connections, and auth status."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "tenant": {
                    "type": "string",
                    "description": "Tenant identity (system-generated)",
                },
            },
            "required": ["tenant"],
            "additionalProperties": False,
        },
        annotations=_RO_ANNOTATIONS,
    ),
    Tool(
        name="ops_probe_connections",
        description=(
            "Run connection probes for a tenant (or all tenants): "
            "XHS API, ERP, runtime, and freshness checks. "
            "This is the ONLY tool that triggers `stonx ctl probe`, "
            "which may write `ops.connection_probe_state` through stonx "
            "(stonex-ops itself never connects to the database)."
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
    Tool(
        name="ops_worker_jobs",
        description=(
            "List worker jobs: queued, running, succeeded, failed, or cancelled "
            "jobs for daily/weekly report generation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "tenant": {
                    "type": "string",
                    "description": "Optional: filter by tenant.",
                },
                "status": {
                    "type": "string",
                    "enum": ["queued", "running", "succeeded", "failed", "cancelled"],
                    "description": "Optional: filter by job status.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Optional: max results (default 50).",
                },
            },
            "additionalProperties": False,
        },
        annotations=_RO_ANNOTATIONS,
    ),
    Tool(
        name="ops_worker_schedules",
        description=(
            "List worker schedules: cron expression, status (active/paused), timezone."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "tenant": {
                    "type": "string",
                    "description": "Optional: filter by tenant.",
                },
            },
            "additionalProperties": False,
        },
        annotations=_RO_ANNOTATIONS,
    ),
    Tool(
        name="ops_report_status",
        description=(
            "Show recent report generation status: "
            "latest successful daily/weekly reports and recent job list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "tenant": {
                    "type": "string",
                    "description": "Optional: filter by tenant.",
                },
            },
            "additionalProperties": False,
        },
        annotations=_RO_ANNOTATIONS,
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
        logger: AuditLogger,
    ) -> None:
        self.stonx_bin = stonx_bin
        self.env = env
        self.path = path
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

    elif name == "ops_tenant_list":
        return await tools.tenant_list(bin_, env, path)

    elif name == "ops_tenant_show":
        tenant = _require_string(arguments, "tenant")
        return await tools.tenant_show(bin_, env, path, tenant)

    elif name == "ops_probe_connections":
        tenant = _optional_string(arguments, "tenant")
        shop_id = _optional_string(arguments, "shop_id")
        return await tools.probe_connections(bin_, env, path, tenant, shop_id)

    elif name == "ops_worker_jobs":
        tenant = _optional_string(arguments, "tenant")
        status = _optional_string(arguments, "status")
        limit = _optional_int(arguments, "limit")
        return await tools.worker_jobs(bin_, env, path, tenant, status, limit)

    elif name == "ops_worker_schedules":
        tenant = _optional_string(arguments, "tenant")
        return await tools.worker_schedules(bin_, env, path, tenant)

    elif name == "ops_report_status":
        tenant = _optional_string(arguments, "tenant")
        return await tools.report_status(bin_, env, path, tenant)

    else:
        raise ValueError(f"unknown tool: {name}")


# ---- MCP Server ----

def _create_server() -> Server:
    """Build the MCP Server with list_tools / call_tool handlers."""
    server = Server("stonex-ops")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOL_DEFINITIONS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        state: ServerState = server.request_context.lifespan_context  # type: ignore[union-attr]

        # Concurrency guard
        if state.semaphore.locked():
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

        async with state.semaphore:
            started = time.monotonic()
            error_msg: Optional[str] = None
            status = AuditStatus.success

            try:
                result = await _execute_tool(state, name, arguments)
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
                state.logger.log(AuditEntry(
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    tool=name,
                    arguments=arguments,
                    result_status=status,
                    error=error_msg,
                    duration_ms=duration_ms,
                    session_id=state.logger.session_id,
                ))

    return server


# ---- Entry point ----

async def run_mcp_server(
    stonx_bin: str,
    env: str,
    path: str,
    audit_file: Optional[str] = None,
) -> None:
    """Start the MCP server (stdio JSON-RPC)."""
    audit_path = Path(audit_file) if audit_file else None
    logger = AuditLogger(audit_path)

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

    state = ServerState(
        stonx_bin=stonx_bin,
        env=env,
        path=path,
        logger=logger,
    )

    server = _create_server()

    async with stdio_server() as (read, write):
        await server.run(
            read,
            write,
            server.create_initialization_options(),
            lifespan_context=state,
        )
