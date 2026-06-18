"""Output redaction: second-pass filter for sensitive fields in JSON output.

Scans every key in a JSON object and replaces matching values with "[redacted]".
"""

from __future__ import annotations

from typing import Any

# Sensitive field name patterns (case-insensitive substring match).
SENSITIVE_KEY_PATTERNS: tuple[str, ...] = (
    "token",
    "secret",
    "password",
    "cookie",
    "authorization",
    "api_key",
    "access_token",
    "refresh_token",
    "session",
    "credential",
)


def is_sensitive_key(key: str) -> bool:
    """Return true when a JSON key or SQL column name looks sensitive."""
    lowered = key.lower()
    return any(pattern in lowered for pattern in SENSITIVE_KEY_PATTERNS)


def redact(value: Any) -> None:
    """Recursively redact sensitive fields in a JSON value (mutates in place)."""
    if isinstance(value, dict):
        keys_to_redact = [k for k in value if is_sensitive_key(k)]
        for k in keys_to_redact:
            value[k] = "[redacted]"
        for v in value.values():
            redact(v)
    elif isinstance(value, list):
        for item in value:
            redact(item)
