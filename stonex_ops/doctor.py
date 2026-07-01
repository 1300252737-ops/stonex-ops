"""doctor: read-only host compatibility check. Must not run probe.

Checks:
- stonx binary exists and is executable (PATH-aware).
- stonx --version works.
- readonly database URL resolves.
- readonly database can inspect schema and execute select 1.
- Audit file directory is writable.
- MCP tool definitions are present.

All checks are read-only. Probe is never invoked.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from stonex_ops.db import resolve_readonly_database_url
from stonex_ops.server import TOOL_DEFINITIONS
from stonex_ops.tools import db_schema, env_check, sql_readonly


@dataclass
class DoctorResult:
    passed: bool = True
    checks: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            self.passed = False


async def run_doctor(
    stonx_bin: str,
    env: str,
    path: str,
    audit_file: Optional[str] = None,
    readonly_database_url: Optional[str] = None,
    readonly_database_url_file: Optional[str] = None,
) -> DoctorResult:
    result = DoctorResult()

    # 1. stonx binary exists and is executable.
    #    For absolute/relative paths, check directly.  For bare names (e.g.
    #    --stonx-bin stonx), search PATH via shutil.which().
    resolved = stonx_bin
    if "/" in stonx_bin:
        stonx_path = Path(stonx_bin)
        if not (stonx_path.is_file() and os.access(stonx_path, os.X_OK)):
            result.add("stonx_binary", False, f"not found or not executable: {stonx_bin}")
            return result
    else:
        found = shutil.which(stonx_bin)
        if found:
            resolved = found
        else:
            result.add("stonx_binary", False, f"not found in PATH: {stonx_bin}")
            return result
    result.add("stonx_binary", True, resolved)

    # 2. stonx --version works
    check = await env_check(stonx_bin, env, path)
    if check["stonx_reachable"]:
        result.add("stonx_version", True, check.get("stonx_version", ""))
    else:
        result.add("stonx_version", False, "stonx --version failed")
        return result

    # 3. Readonly DB capability used by ops_db_schema / ops_sql_readonly.
    try:
        resolved_readonly_url = resolve_readonly_database_url(
            path=path,
            env=env,
            readonly_database_url=readonly_database_url,
            readonly_database_url_file=readonly_database_url_file,
        )
        result.add("readonly_database_url", True, "resolved")
    except Exception as exc:
        result.add("readonly_database_url", False, f"{type(exc).__name__}: {exc}")
        return result

    try:
        schema_result = await db_schema(resolved_readonly_url)
        result.add(
            "ops_db_schema",
            schema_result.get("table_count", 0) > 0,
            f"{schema_result.get('table_count', 0)} tables visible",
        )
    except Exception as exc:
        result.add("ops_db_schema", False, f"{type(exc).__name__}: {exc}")
        return result

    try:
        query_result = await sql_readonly(resolved_readonly_url, "select 1 as ok", 1)
        ok = query_result.get("rows") == [[1]]
        result.add("ops_sql_readonly", ok, "select 1")
    except Exception as exc:
        result.add("ops_sql_readonly", False, f"{type(exc).__name__}: {exc}")
        return result

    # 4. Audit file is writable (directory + file itself)
    if audit_file:
        audit_path = Path(audit_file)
        audit_dir = audit_path.parent
        try:
            # Check directory
            ok = audit_dir.is_dir() and os.access(str(audit_dir), os.W_OK)
            if ok and audit_path.exists():
                ok = os.access(str(audit_path), os.W_OK)
            if not ok and not audit_path.exists():
                # Try to create it to verify writability
                try:
                    audit_path.touch()
                    audit_path.unlink()
                    ok = True
                except OSError:
                    ok = False
            result.add("audit_file", ok, str(audit_path) if ok else f"not writable: {audit_path}")
        except Exception as exc:
            result.add("audit_file", False, str(exc))
    else:
        result.add("audit_file", True, f"default: {Path(path)}")

    # 5. MCP tool definitions are present
    tool_names = [t.name for t in TOOL_DEFINITIONS]
    expected_tools = {
        "ops_env_check",
        "ops_db_schema",
        "ops_sql_readonly",
        "ops_probe_connections",
        "ops_notification_publish",
    }
    if set(tool_names) == expected_tools:
        result.add(
            "mcp_tools", True,
            f"{len(tool_names)} tools: {', '.join(tool_names)}",
        )
    else:
        result.add("mcp_tools", False, f"unexpected tools: {', '.join(tool_names)}")

    return result


def run_doctor_sync(
    stonx_bin: str,
    env: str,
    path: str,
    audit_file: Optional[str] = None,
    readonly_database_url: Optional[str] = None,
    readonly_database_url_file: Optional[str] = None,
) -> DoctorResult:
    """Sync wrapper for CLI usage."""
    import asyncio
    return asyncio.run(
        run_doctor(
            stonx_bin,
            env,
            path,
            audit_file,
            readonly_database_url,
            readonly_database_url_file,
        )
    )
