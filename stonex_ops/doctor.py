"""doctor: read-only host compatibility check. Must not run probe.

Checks:
- stonx binary exists and is executable (PATH-aware).
- stonx --version works.
- Required `ctl ... --output json` contracts are available
  (capability probe, not version-string check).
- Audit file directory is writable.
- MCP tool definitions are present.

All checks are read-only. Probe is never invoked.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from stonex_ops.executor import ExecutionError, execute
from stonex_ops.server import TOOL_DEFINITIONS
from stonex_ops.tools import env_check
from stonex_ops.whitelist import TenantList, WorkerJobList, WorkerScheduleList


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

    # 3. Compatibility: verify key read-only `ctl ... --output json` contracts
    #    used by the MCP tools (tenant list, worker jobs, worker schedules).
    ctl_contracts: list[tuple[str, Any]] = [
        ("tenant_list", TenantList()),
        ("worker_jobs", WorkerJobList(limit=1)),
        ("worker_schedules", WorkerScheduleList()),
    ]
    all_ok = True
    for label, cmd in ctl_contracts:
        try:
            output = await execute(stonx_bin, env, path, cmd)
            json.loads(output)  # must be valid JSON
            result.add(f"stonx_ctl_{label}", True, "ok")
        except ExecutionError as exc:
            all_ok = False
            result.add(f"stonx_ctl_{label}", False, str(exc))
        except Exception as exc:
            all_ok = False
            result.add(f"stonx_ctl_{label}", False, f"{type(exc).__name__}: {exc}")
    if not all_ok:
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
    if len(tool_names) >= 6:
        result.add(
            "mcp_tools", True,
            f"{len(tool_names)} tools: {', '.join(tool_names)}",
        )
    else:
        result.add("mcp_tools", False, f"only {len(tool_names)} tools found")

    return result


def run_doctor_sync(
    stonx_bin: str,
    env: str,
    path: str,
    audit_file: Optional[str] = None,
) -> DoctorResult:
    """Sync wrapper for CLI usage."""
    import asyncio
    return asyncio.run(run_doctor(stonx_bin, env, path, audit_file))
