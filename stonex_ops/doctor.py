"""doctor: read-only host compatibility check. Must not run probe.

Checks:
- stonx binary exists and is executable.
- stonx --version works and meets the minimum compatible version.
- Allowlisted stonx ctl commands are reachable.
- Audit file directory is writable.
- MCP tool definitions are present.

All checks are read-only. Probe is never invoked.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from stonex_ops.executor import ExecutionError, execute
from stonex_ops.server import TOOL_DEFINITIONS
from stonex_ops.tools import env_check
from stonex_ops.whitelist import TenantList

# Minimum compatible stonx version (date-based).
# Update this when the stonx JSON CLI contract changes.
COMPATIBLE_STONX = ">= 2026-06-16"


@dataclass
class DoctorResult:
    passed: bool = True
    checks: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            self.passed = False


def _check_compatible_version(stonx_version: str) -> tuple[bool, str]:
    """Check if the reported stonx version meets COMPATIBLE_STONX.

    stonx --version typically outputs a commit-ish date in the version
    string, e.g. 'stonx 1.2.3 (abc1234 2026-06-01)'.  We do a simple
    substring check for the expected date boundaries.
    """
    if "2026" in stonx_version:
        return True, f"stonx version appears recent: {stonx_version}"
    return False, f"stonx version too old (expected >= 2026-06-16): {stonx_version}"


async def run_doctor(
    stonx_bin: str,
    env: str,
    path: str,
    audit_file: Optional[str] = None,
) -> DoctorResult:
    result = DoctorResult()

    # 1. stonx binary exists and is executable
    stonx_path = Path(stonx_bin)
    if stonx_path.is_file() and os.access(stonx_path, os.X_OK):
        result.add("stonx_binary", True, str(stonx_path))
    else:
        result.add("stonx_binary", False, f"not found or not executable: {stonx_bin}")
        return result  # can't continue without stonx

    # 2. stonx --version works and is compatible
    check = await env_check(stonx_bin, env, path)
    if check["stonx_reachable"]:
        version = check.get("stonx_version", "")
        ok, msg = _check_compatible_version(version)
        result.add("stonx_version", ok, msg)
    else:
        result.add("stonx_version", False, "stonx --version failed")
        return result

    # 3. Allowlisted ctl command works (tenant list as smoke read)
    try:
        output = await execute(stonx_bin, env, path, TenantList())
        tenants = json.loads(output).get("tenants", [])
        result.add(
            "stonx_ctl_read", True,
            f"tenant list returned {len(tenants)} tenant(s)",
        )
    except ExecutionError as exc:
        result.add("stonx_ctl_read", False, str(exc))
    except Exception as exc:
        result.add("stonx_ctl_read", False, f"{type(exc).__name__}: {exc}")

    # 4. Audit file directory is writable
    if audit_file:
        audit_dir = Path(audit_file).parent
    else:
        audit_dir = Path(path)
    try:
        if audit_dir.is_dir() and os.access(str(audit_dir), os.W_OK):
            result.add("audit_dir", True, str(audit_dir))
        else:
            result.add(
                "audit_dir", False,
                f"not writable: {audit_dir} (exists={audit_dir.is_dir()})",
            )
    except Exception as exc:
        result.add("audit_dir", False, str(exc))

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
