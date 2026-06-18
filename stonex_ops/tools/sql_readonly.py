"""ops_sql_readonly: execute caller-provided SQL via readonly DB role."""

from __future__ import annotations

from typing import Any

from stonex_ops.db import execute_sql


async def run(readonly_database_url: str, sql: str, max_rows: int) -> dict[str, Any]:
    return await execute_sql(readonly_database_url, sql=sql, max_rows=max_rows)
