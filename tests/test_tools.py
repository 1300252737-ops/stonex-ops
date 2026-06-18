"""Tests for MCP tool definitions and argument validation."""

import asyncio
import inspect

import pytest

from stonex_ops.db import (
    DEFAULT_MAX_ROWS,
    MAX_MAX_ROWS,
    REDACTED,
    _collect_current_result_set,
    _with_timeout,
    derive_readonly_database_url,
)
from stonex_ops.server import (
    TOOL_DEFINITIONS,
    _max_rows,
    _optional_int,
    _optional_string,
    _require_string,
)


def test_tool_set_is_minimal():
    names = [tool.name for tool in TOOL_DEFINITIONS]
    assert names == [
        "ops_env_check",
        "ops_db_schema",
        "ops_sql_readonly",
        "ops_probe_connections",
    ]


def test_sql_tool_schema_requires_sql_and_caps_max_rows():
    tool = next(tool for tool in TOOL_DEFINITIONS if tool.name == "ops_sql_readonly")
    assert tool.inputSchema["required"] == ["sql"]
    assert tool.inputSchema["properties"]["max_rows"]["maximum"] == MAX_MAX_ROWS


def test_probe_tool_annotations_are_not_read_only():
    tool = next(t for t in TOOL_DEFINITIONS if t.name == "ops_probe_connections")
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is False


def test_readonly_tools_are_marked_read_only():
    for name in ["ops_env_check", "ops_db_schema", "ops_sql_readonly"]:
        tool = next(t for t in TOOL_DEFINITIONS if t.name == name)
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False


def test_require_string_rejects_non_string():
    with pytest.raises(ValueError, match="must be a non-empty string"):
        _require_string({"sql": 123}, "sql")
    with pytest.raises(ValueError, match="must be a non-empty string"):
        _require_string({"sql": None}, "sql")
    with pytest.raises(ValueError, match="must be a non-empty string"):
        _require_string({"sql": True}, "sql")


def test_optional_string_rejects_non_string():
    with pytest.raises(ValueError, match="must be a string"):
        _optional_string({"schema": 123}, "schema")
    with pytest.raises(ValueError, match="must be a string"):
        _optional_string({"schema": True}, "schema")
    assert _optional_string({"schema": None}, "schema") is None
    assert _optional_string({}, "schema") is None


def test_optional_int_rejects_non_int():
    with pytest.raises(ValueError, match="must be an integer"):
        _optional_int({"max_rows": "abc"}, "max_rows")
    with pytest.raises(ValueError, match="must be an integer"):
        _optional_int({"max_rows": True}, "max_rows")
    assert _optional_int({"max_rows": None}, "max_rows") is None
    assert _optional_int({}, "max_rows") is None
    assert _optional_int({"max_rows": 50}, "max_rows") == 50


def test_max_rows_defaults_and_validates_range():
    assert _max_rows({}) == DEFAULT_MAX_ROWS
    assert _max_rows({"max_rows": 1}) == 1
    assert _max_rows({"max_rows": MAX_MAX_ROWS}) == MAX_MAX_ROWS
    with pytest.raises(ValueError, match="max_rows must be between"):
        _max_rows({"max_rows": 0})
    with pytest.raises(ValueError, match="max_rows must be between"):
        _max_rows({"max_rows": MAX_MAX_ROWS + 1})


def test_derives_readonly_database_url_from_stonx_database_url():
    assert (
        derive_readonly_database_url("postgresql://postgres@127.0.0.1:55432/stonex_dev")
        == "postgresql://stonex_ops_readonly@127.0.0.1:55432/stonex_dev"
    )
    assert (
        derive_readonly_database_url(
            "postgresql://app:secret@[::1]:55432/stonex_dev?application_name=stonx"
        )
        == "postgresql://stonex_ops_readonly@[::1]:55432/stonex_dev?application_name=stonx"
    )


@pytest.mark.anyio
async def test_sql_result_redacts_sensitive_columns():
    class Column:
        def __init__(self, name: str) -> None:
            self.name = name

    class Cursor:
        description = [Column("tenant_id"), Column("access_token"), Column("refresh_secret")]
        statusmessage = "SELECT 1"

        async def fetchmany(self, _size: int):
            return [["tn_demo", "token-value", "secret-value"]]

    result = await _collect_current_result_set(Cursor(), 10)
    assert result["columns"] == ["tenant_id", "access_token", "refresh_secret"]
    assert result["rows"] == [["tn_demo", REDACTED, REDACTED]]


@pytest.mark.anyio
async def test_sql_timeout_is_enforced(monkeypatch):
    async def slow():
        await asyncio.sleep(0.1)

    import stonex_ops.db as db

    monkeypatch.setattr(db, "SQL_TIMEOUT_SECONDS", 0.001)
    with pytest.raises(TimeoutError, match="execute SQL timed out"):
        await _with_timeout(slow(), "execute SQL")


def test_env_check_does_not_construct_probe():
    from stonex_ops.tools.env_check import run as _env_check

    src = inspect.getsource(_env_check)
    assert "StonxVersion" in src
    assert "Probe" not in src


def test_only_probe_connections_constructs_probe():
    from stonex_ops.tools import probe_connections as _pc

    src = inspect.getsource(_pc)
    assert "Probe(" in src or "ProbeAll(" in src


def test_non_probe_tools_do_not_construct_probe():
    from stonex_ops.tools import db_schema, env_check, sql_readonly

    for fn in [db_schema, env_check, sql_readonly]:
        src = inspect.getsource(fn)
        assert "Probe(" not in src, f"{fn.__name__} must not construct Probe"
        assert "ProbeAll(" not in src, f"{fn.__name__} must not construct ProbeAll"
