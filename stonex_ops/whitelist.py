"""Command allowlist: permitted `stonx ctl` commands with parameter limits.

Upstream CLI contract: `stonx ctl <subcommand> --output json [...]`
`--output json` is a subcommand-level flag, not a global flag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_IDENTITY_RE = re.compile(r"^[a-zA-Z0-9\-_]{1,128}$")
_VALID_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "cancelled"})


def is_safe_identity(value: str) -> bool:
    """Validate tenant / shop_id character set and length."""
    return bool(_IDENTITY_RE.match(value))


# ---- command classes ----


@dataclass(frozen=True)
class TenantList:
    """stonx ctl tenant list --output json"""

    def to_args(self, stonx_bin: str, env: str, path: str) -> list[str]:
        return [
            stonx_bin, f"--env={env}", f"--path={path}",
            "ctl", "tenant", "list", "--output=json",
        ]


@dataclass(frozen=True)
class TenantShow:
    """stonx ctl tenant show --tenant <id> --output json"""

    tenant: str

    def to_args(self, stonx_bin: str, env: str, path: str) -> list[str]:
        if not is_safe_identity(self.tenant):
            raise ValueError(
                f"invalid tenant identity: {self.tenant}. "
                "Must be alphanumeric, hyphens, or underscores, max 128 chars."
            )
        return [
            stonx_bin, f"--env={env}", f"--path={path}", "ctl",
            "tenant", "show", f"--tenant={self.tenant}", "--output=json",
        ]


@dataclass(frozen=True)
class Probe:
    """stonx ctl probe [--tenant <id>] [--shop-id <id>] --output json"""

    tenant: Optional[str] = None
    shop_id: Optional[str] = None

    def to_args(self, stonx_bin: str, env: str, path: str) -> list[str]:
        args = [stonx_bin, f"--env={env}", f"--path={path}", "ctl", "probe"]
        if self.tenant:
            if not is_safe_identity(self.tenant):
                raise ValueError(
                    f"invalid tenant identity: {self.tenant}. "
                    "Must be alphanumeric, hyphens, or underscores, max 128 chars."
                )
            args.append(f"--tenant={self.tenant}")
        if self.shop_id:
            if not is_safe_identity(self.shop_id):
                raise ValueError(
                    f"invalid shop_id: {self.shop_id}. "
                    "Must be alphanumeric, hyphens, or underscores, max 128 chars."
                )
            args.append(f"--shop-id={self.shop_id}")
        args.append("--output=json")
        return args


@dataclass(frozen=True)
class WorkerScheduleList:
    """stonx ctl worker schedule list [--tenant <id>] --output json"""

    tenant: Optional[str] = None

    def to_args(self, stonx_bin: str, env: str, path: str) -> list[str]:
        args = [
            stonx_bin, f"--env={env}", f"--path={path}",
            "ctl", "worker", "schedule", "list",
        ]
        if self.tenant:
            if not is_safe_identity(self.tenant):
                raise ValueError(
                    f"invalid tenant identity: {self.tenant}. "
                    "Must be alphanumeric, hyphens, or underscores, max 128 chars."
                )
            args.append(f"--tenant={self.tenant}")
        args.append("--output=json")
        return args


@dataclass(frozen=True)
class WorkerJobList:
    """stonx ctl worker job list [--tenant <id>] [--status <s>] [--limit <n>] --output json"""

    tenant: Optional[str] = None
    status: Optional[str] = None
    limit: Optional[int] = None

    def to_args(self, stonx_bin: str, env: str, path: str) -> list[str]:
        args = [
            stonx_bin, f"--env={env}", f"--path={path}",
            "ctl", "worker", "job", "list",
        ]
        if self.tenant:
            if not is_safe_identity(self.tenant):
                raise ValueError(
                    f"invalid tenant identity: {self.tenant}. "
                    "Must be alphanumeric, hyphens, or underscores, max 128 chars."
                )
            args.append(f"--tenant={self.tenant}")
        if self.status:
            if self.status not in _VALID_STATUSES:
                raise ValueError(
                    f"invalid job status: {self.status}. "
                    "Valid: queued, running, succeeded, failed, cancelled."
                )
            args.append(f"--status={self.status}")
        if self.limit is not None:
            if self.limit < 1 or self.limit > 500:
                raise ValueError(
                    f"limit out of range: {self.limit}. Must be 1-500."
                )
            args.append(f"--limit={self.limit}")
        args.append("--output=json")
        return args


@dataclass(frozen=True)
class StonxVersion:
    """stonx --version"""

    def to_args(self, stonx_bin: str, env: str, path: str) -> list[str]:
        return [stonx_bin, "--version"]


@dataclass(frozen=True)
class ProbeAll:
    """stonx ctl probe --output json (all active scopes)"""

    def to_args(self, stonx_bin: str, env: str, path: str) -> list[str]:
        return [
            stonx_bin, f"--env={env}", f"--path={path}",
            "ctl", "probe", "--output=json",
        ]


# Discriminated union type
AllowedCommand = (
    TenantList | TenantShow | Probe | WorkerScheduleList
    | WorkerJobList | StonxVersion | ProbeAll
)


def op_kind(cmd: AllowedCommand) -> str:
    """Return the operation kind (determines timeout)."""
    if isinstance(cmd, (StonxVersion,)):
        return "read"
    if isinstance(cmd, (Probe, ProbeAll)):
        return "probe"
    return "read"
