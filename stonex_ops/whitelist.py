"""Command allowlist for the remaining stonx subprocess calls.

Read-only analysis uses PostgreSQL directly. The allowlist only covers
`stonx --version` and active `stonx ctl probe` calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_IDENTITY_RE = re.compile(r"^[a-zA-Z0-9\-_]{1,128}$")


def is_safe_identity(value: str) -> bool:
    """Validate tenant / shop_id character set and length."""
    return bool(_IDENTITY_RE.match(value))


# ---- command classes ----


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
AllowedCommand = Probe | StonxVersion | ProbeAll


def op_kind(cmd: AllowedCommand) -> str:
    """Return the operation kind (determines timeout)."""
    if isinstance(cmd, (StonxVersion,)):
        return "read"
    if isinstance(cmd, (Probe, ProbeAll)):
        return "probe"
    return "read"
