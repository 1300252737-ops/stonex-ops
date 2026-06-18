"""ops_db_schema: inspect PostgreSQL schema visible to stonex_ops_readonly."""

from __future__ import annotations

from typing import Any, Optional

from stonex_ops.db import inspect_schema


async def run(
    readonly_database_url: str,
    schema: Optional[str] = None,
    table: Optional[str] = None,
) -> dict[str, Any]:
    return await inspect_schema(readonly_database_url, schema=schema, table=table)
