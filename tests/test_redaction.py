"""Tests for output redaction."""

import copy

from stonex_ops.redaction import redact


def test_redacts_token_fields():
    value = {
        "status": "ok",
        "access_token": "secret-abc-123",
        "data": {
            "name": "test",
            "api_key": "sk-12345",
        },
    }
    redact(value)
    assert value["access_token"] == "[redacted]"
    assert value["data"]["api_key"] == "[redacted]"
    assert value["data"]["name"] == "test"


def test_redacts_nested_sensitive_fields():
    value = {
        "connections": [
            {"name": "xhs", "token": "abc"},
            {"name": "jst", "session": "xyz"},
        ]
    }
    redact(value)
    assert value["connections"][0]["token"] == "[redacted]"
    assert value["connections"][1]["session"] == "[redacted]"


def test_preserves_non_sensitive_fields():
    value = {
        "tenant": "test-123",
        "status": "active",
        "updated_at": "2026-06-16",
    }
    original = copy.deepcopy(value)
    redact(value)
    assert value == original
