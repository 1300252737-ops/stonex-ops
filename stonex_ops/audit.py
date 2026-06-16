"""Audit log: records who / when / what / result for every MCP tool call.

Format: JSONL (one line per entry), written to stderr and an optional file.
"""

from __future__ import annotations

import json
import sys
import threading
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional, TextIO


class AuditStatus(str, Enum):
    success = "success"
    execution_failed = "execution_failed"


@dataclass
class AuditEntry:
    timestamp: str
    tool: str
    arguments: dict[str, Any]
    result_status: AuditStatus
    error: Optional[str]
    duration_ms: int
    session_id: str


class AuditLogger:
    """Thread-safe JSONL audit logger."""

    def __init__(self, audit_file: Optional[Path] = None) -> None:
        self._session_id = str(uuid.uuid4())
        self._lock = threading.Lock()
        self._file: Optional[TextIO] = None
        if audit_file:
            self._file = open(audit_file, "a", encoding="utf-8")  # noqa: SIM115

    @property
    def session_id(self) -> str:
        return self._session_id

    def log(self, entry: AuditEntry) -> None:
        line = json.dumps(asdict(entry), ensure_ascii=False)
        with self._lock:
            if self._file:
                self._file.write(line + "\n")
                self._file.flush()
        # Always write to stderr for dev visibility.
        print(f"[audit] {line}", file=sys.stderr)

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
