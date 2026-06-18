"""PostgreSQL readonly helpers for stonex-ops.

stonex-ops intentionally does not maintain business SQL templates. It exposes
schema introspection plus a readonly SQL executor backed by the
`stonex_ops_readonly` database role.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import decimal
import json
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from stonex_ops.redaction import is_sensitive_key

READONLY_ROLE = "stonex_ops_readonly"
DEFAULT_MAX_ROWS = 200
MAX_MAX_ROWS = 2000
REDACTED = "[redacted]"
SQL_TIMEOUT_SECONDS = 5.0
USER_SCHEMA_SQL = """
    select nspname
    from pg_namespace
    where nspname <> 'information_schema'
      and nspname !~ '^pg_'
    order by nspname
"""
VISIBLE_TABLE_COUNT_SQL = """
    select count(*)
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname <> 'information_schema'
      and n.nspname !~ '^pg_'
      and c.relkind in ('r', 'v', 'm', 'p')
      and has_schema_privilege(n.oid, 'usage')
      and has_table_privilege(c.oid, 'select')
"""


def config_path(path: str, env: str) -> Path:
    """Return the stonx config path for an env root."""
    return Path(path).joinpath(env, "config.toml")


def database_url_from_config(path: str, env: str) -> str:
    """Read `[database].url` from stonx config."""
    file = config_path(path, env)
    with file.open("rb") as fh:
        data = tomllib.load(fh)
    try:
        url = data["database"]["url"]
    except KeyError as exc:
        raise ValueError(f"missing [database].url in {file}") from exc
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f"[database].url must be a non-empty string in {file}")
    return url.strip()


def derive_readonly_database_url(database_url: str) -> str:
    """Replace the connection username with the readonly role.

    Existing host, port, database path, query parameters, and fragment are
    preserved. Passwords from the application URL are intentionally dropped.
    """
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError(f"unsupported PostgreSQL URL scheme: {parsed.scheme}")

    host = parsed.hostname
    if host:
        host_part = f"[{host}]" if ":" in host and not host.startswith("[") else host
        port_part = f":{parsed.port}" if parsed.port else ""
        netloc = f"{quote(READONLY_ROLE)}@{host_part}{port_part}"
    else:
        netloc = quote(READONLY_ROLE)

    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def resolve_readonly_database_url(
    *,
    path: str,
    env: str,
    readonly_database_url: Optional[str] = None,
    readonly_database_url_file: Optional[str] = None,
) -> str:
    """Resolve the readonly DB URL from explicit value, file, or stonx config."""
    if readonly_database_url and readonly_database_url.strip():
        return readonly_database_url.strip()

    if readonly_database_url_file and readonly_database_url_file.strip():
        file = Path(readonly_database_url_file)
        value = file.read_text(encoding="utf-8").strip()
        if not value:
            raise ValueError(f"readonly database URL file is empty: {file}")
        return value

    return derive_readonly_database_url(database_url_from_config(path, env))


def bootstrap_readonly_role(database_url: str) -> dict[str, Any]:
    """Create or repair the readonly role required by ops SQL tools."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(USER_SCHEMA_SQL)
            schemas = [row[0] for row in cur.fetchall()]

            cur.execute("select exists(select 1 from pg_roles where rolname = %s)", [READONLY_ROLE])
            existed = bool(cur.fetchone()[0])
            if not existed:
                cur.execute(
                    sql.SQL("create role {} login").format(sql.Identifier(READONLY_ROLE))
                )

            cur.execute(
                sql.SQL("alter role {} set default_transaction_read_only = on").format(
                    sql.Identifier(READONLY_ROLE)
                )
            )
            cur.execute("select current_database()")
            database_name = cur.fetchone()[0]
            cur.execute(
                sql.SQL("grant connect on database {} to {}").format(
                    sql.Identifier(database_name),
                    sql.Identifier(READONLY_ROLE),
                )
            )

            for schema in schemas:
                schema_ident = sql.Identifier(schema)
                role_ident = sql.Identifier(READONLY_ROLE)
                cur.execute(
                    sql.SQL("grant usage on schema {} to {}").format(
                        schema_ident,
                        role_ident,
                    )
                )
                cur.execute(
                    sql.SQL("grant select on all tables in schema {} to {}").format(
                        schema_ident,
                        role_ident,
                    )
                )
                cur.execute(
                    sql.SQL(
                        "alter default privileges in schema {} grant select on tables to {}"
                    ).format(
                        schema_ident,
                        role_ident,
                    )
                )

    readonly_url = derive_readonly_database_url(database_url)
    with psycopg.connect(readonly_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("show default_transaction_read_only")
            read_only = cur.fetchone()[0] == "on"
            cur.execute(VISIBLE_TABLE_COUNT_SQL)
            visible_tables = int(cur.fetchone()[0])

    if not read_only:
        raise RuntimeError(f"{READONLY_ROLE} is not forced read-only")
    if visible_tables < 1:
        raise RuntimeError(f"{READONLY_ROLE} cannot see any user tables")

    return {
        "role": READONLY_ROLE,
        "created": not existed,
        "schemas": schemas,
        "visible_tables": visible_tables,
        "read_only": read_only,
    }


async def inspect_schema(
    readonly_database_url: str,
    *,
    schema: Optional[str] = None,
    table: Optional[str] = None,
) -> dict[str, Any]:
    """Return schema/table metadata visible to the readonly role."""
    if table and "." in table and schema is None:
        schema, table = table.split(".", 1)

    if table:
        if not schema:
            raise ValueError("schema is required when table is provided")
        return await _inspect_table(readonly_database_url, schema, table)
    return await _list_tables(readonly_database_url, schema)


async def execute_sql(
    readonly_database_url: str,
    *,
    sql: str,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> dict[str, Any]:
    """Execute caller SQL via the readonly role and return JSON-safe rows."""
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql must be a non-empty string")
    if max_rows < 1 or max_rows > MAX_MAX_ROWS:
        raise ValueError(f"max_rows must be between 1 and {MAX_MAX_ROWS}")

    started = time.monotonic()
    result_sets: list[dict[str, Any]] = []
    conn = await _connect(readonly_database_url)
    try:
        await _with_timeout(conn.execute("set statement_timeout = '5s'"), "set statement_timeout")
        async with conn.cursor() as cur:
            await _with_timeout(cur.execute(sql), "execute SQL")
            while True:
                result_sets.append(await _collect_current_result_set(cur, max_rows))
                has_next = cur.nextset()
                if not has_next:
                    break
    finally:
        await conn.close()

    duration_ms = int((time.monotonic() - started) * 1000)
    first = result_sets[0] if result_sets else _empty_result_set()
    return {
        "columns": first["columns"],
        "rows": first["rows"],
        "row_count": first["row_count"],
        "truncated": first["truncated"],
        "command_status": first["command_status"],
        "result_sets": result_sets,
        "duration_ms": duration_ms,
    }


async def _list_tables(readonly_database_url: str, schema: Optional[str]) -> dict[str, Any]:
    sql = """
        select
            n.nspname as schema,
            c.relname as table,
            case c.relkind
                when 'r' then 'table'
                when 'v' then 'view'
                when 'm' then 'materialized_view'
                when 'p' then 'partitioned_table'
                else c.relkind::text
            end as kind,
            obj_description(c.oid) as comment
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname <> 'information_schema'
          and n.nspname !~ '^pg_'
          and c.relkind in ('r', 'v', 'm', 'p')
          and has_schema_privilege(n.oid, 'usage')
          and has_table_privilege(c.oid, 'select')
          and (%s::text is null or n.nspname = %s)
        order by n.nspname, c.relname
    """
    rows = await _fetch_dicts(readonly_database_url, sql, [schema, schema])
    return {"schema": schema, "tables": rows, "table_count": len(rows)}


async def _inspect_table(readonly_database_url: str, schema: str, table: str) -> dict[str, Any]:
    table_sql = """
        select
            n.nspname as schema,
            c.relname as table,
            case c.relkind
                when 'r' then 'table'
                when 'v' then 'view'
                when 'm' then 'materialized_view'
                when 'p' then 'partitioned_table'
                else c.relkind::text
            end as kind,
            obj_description(c.oid) as comment
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = %s
          and c.relname = %s
          and c.relkind in ('r', 'v', 'm', 'p')
          and has_schema_privilege(n.oid, 'usage')
          and has_table_privilege(c.oid, 'select')
    """
    tables = await _fetch_dicts(readonly_database_url, table_sql, [schema, table])
    if not tables:
        raise ValueError(f"table not found or not visible: {schema}.{table}")

    columns_sql = """
        select
            a.attname as name,
            format_type(a.atttypid, a.atttypmod) as type,
            a.attnotnull as not_null,
            pg_get_expr(d.adbin, d.adrelid) as default,
            col_description(a.attrelid, a.attnum) as comment
        from pg_attribute a
        join pg_class c on c.oid = a.attrelid
        join pg_namespace n on n.oid = c.relnamespace
        left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
        where n.nspname = %s
          and c.relname = %s
          and a.attnum > 0
          and not a.attisdropped
        order by a.attnum
    """
    indexes_sql = """
        select
            i.relname as index_name,
            ix.indisprimary as primary,
            ix.indisunique as unique,
            pg_get_indexdef(ix.indexrelid) as definition
        from pg_index ix
        join pg_class t on t.oid = ix.indrelid
        join pg_class i on i.oid = ix.indexrelid
        join pg_namespace n on n.oid = t.relnamespace
        where n.nspname = %s
          and t.relname = %s
        order by ix.indisprimary desc, ix.indisunique desc, i.relname
    """
    columns = await _fetch_dicts(readonly_database_url, columns_sql, [schema, table])
    indexes = await _fetch_dicts(readonly_database_url, indexes_sql, [schema, table])
    primary_key = [
        column
        for index in indexes
        if index.get("primary")
        for column in _index_columns(index.get("definition"))
    ]
    return {
        **tables[0],
        "columns": columns,
        "indexes": indexes,
        "primary_key": primary_key,
    }


async def _fetch_dicts(
    readonly_database_url: str,
    sql: str,
    params: list[Any],
) -> list[dict[str, Any]]:
    conn = await _connect(readonly_database_url)
    try:
        await _with_timeout(conn.execute("set statement_timeout = '5s'"), "set statement_timeout")
        async with conn.cursor(row_factory=dict_row) as cur:
            await _with_timeout(cur.execute(sql, params), "inspect schema")
            rows = await _with_timeout(cur.fetchall(), "fetch schema")
            return [_json_safe(row) for row in rows]
    finally:
        await conn.close()


async def _collect_current_result_set(cur: psycopg.AsyncCursor, max_rows: int) -> dict[str, Any]:
    if cur.description is None:
        return {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "command_status": cur.statusmessage,
        }

    columns = [column.name for column in cur.description]
    fetched = await _with_timeout(cur.fetchmany(max_rows + 1), "fetch SQL rows")
    truncated = len(fetched) > max_rows
    sensitive_indexes = {idx for idx, column in enumerate(columns) if is_sensitive_key(column)}
    rows = [
        [
            REDACTED if idx in sensitive_indexes else _json_safe(value)
            for idx, value in enumerate(row)
        ]
        for row in fetched[:max_rows]
    ]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "command_status": cur.statusmessage,
    }


def _empty_result_set() -> dict[str, Any]:
    return {
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "command_status": "",
    }


async def _connect(readonly_database_url: str) -> psycopg.AsyncConnection:
    return await _with_timeout(
        psycopg.AsyncConnection.connect(readonly_database_url, autocommit=True),
        "connect to PostgreSQL",
    )


async def _with_timeout(awaitable, action: str):
    try:
        return await asyncio.wait_for(awaitable, timeout=SQL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"{action} timed out after {SQL_TIMEOUT_SECONDS:g}s") from exc


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _index_columns(definition: Any) -> list[str]:
    if not isinstance(definition, str):
        return []
    start = definition.find("(")
    end = definition.rfind(")")
    if start < 0 or end <= start:
        return []
    raw = definition[start + 1:end]
    return [part.strip().strip('"') for part in raw.split(",") if part.strip()]
