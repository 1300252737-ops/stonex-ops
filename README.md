# stonex-ops

Standalone ops diagnostics MCP server. Read-only analysis goes through a local
PostgreSQL `stonex_ops_readonly` role; active probes still go through
`stonx ctl probe`.

## Architecture

```
MCP client / agent
  -> stonex-ops MCP server (stdio JSON-RPC)
  -> readonly PostgreSQL schema/SQL tools
  -> allowlisted stonx ctl probe for active connection checks
```

## Key principles

- No dependency on stonex source.
- No query registry: callers write SQL after inspecting schema.
- PostgreSQL readonly role, DB timeout, client timeout, and output redaction are
  the SQL safety boundary.
- Audit log every MCP tool call.
- One explicit active probe tool.

## Probe boundary

Only `ops_probe_connections` triggers `stonx ctl probe`, which may write
`ops.connection_probe_state` **through stonx**. No other tool starts a probe:
not at server startup, not from `ops_env_check`, not from schema/SQL tools.

## Install

```bash
pip install -e .
```

## Usage

### Local (stdio MCP)

```bash
stonex-ops mcp --stonx-bin /path/to/stonx --env test
```

### SSH remote (production HK main)

```bash
ssh -T x-001@<target-host> /stonex/bin/stonex-ops mcp \
  --stonx-bin /stonex/bin/stonx \
  --env main \
  --path /stonex \
  --audit-file /stonex/ops/logs/audit.jsonl
```

Claude Code MCP config:

```json
{
  "mcpServers": {
    "stonex-ops": {
      "command": "ssh",
      "args": [
        "-T", "x-001@<target-host>",
        "/stonex/bin/stonex-ops", "mcp",
        "--stonx-bin", "/stonex/bin/stonx",
        "--env", "main",
        "--path", "/stonex",
        "--audit-file", "/stonex/ops/logs/audit.jsonl"
      ]
    }
  }
}
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `ops_env_check` | Verify stonx binary reachable, show version. Does NOT run probe. |
| `ops_db_schema` | Inspect PostgreSQL schemas, tables, columns, and indexes visible to `stonex_ops_readonly`. |
| `ops_sql_readonly` | Execute caller-provided SQL through the readonly role; results are row-capped and sensitive columns are redacted for MCP output. |
| `ops_probe_connections` | Run provider, freshness, report, AI, and mail probes (may write probe state through stonx). |

## Audit

Every tool call is recorded as a JSONL line to stderr (and an optional
`--audit-file`):

```json
{"timestamp":"2026-06-16T10:00:00Z","tool":"ops_sql_readonly","arguments":{...},"result_status":"success","duration_ms":230,"session_id":"...","operator":"x-001"}
```

### Doctor (host compatibility check)

```bash
stonex-ops doctor \
  --stonx-bin /stonex/bin/stonx \
  --env test \
  --path /stonex/data \
  --audit-file /stonex/ops/logs/audit.jsonl
```

Read-only. Never runs probe. Checks: stonx binary reachable, readonly DB URL
resolves, schema introspection works, `select 1` works, audit directory is
writable, MCP tools are defined.

## Deploy

```bash
release=/stonex/ops/releases/<version>
wheel=stonex_ops-<version>-py3-none-any.whl

mkdir -p "$release" /stonex/ops/logs
cp "$wheel" "$release/"
# CI builds site.tar.gz with all Python dependencies.
mkdir -p "$release/site"
tar -xzf "$release/site.tar.gz" -C "$release/site"

# Smoke before switching
"$release/stonex-ops" doctor --stonx-bin /stonex/bin/stonx ...

# Switch
ln -sfn "$release" /stonex/ops/current
ln -sfn /stonex/ops/current/stonex-ops /stonex/bin/stonex-ops
```

## Testing

```bash
pytest
```

## Security

- **Command allowlist**: only predefined `stonx --version` and `stonx ctl probe`
  subprocess calls.
- **Input validation**: MCP argument types and probe identities are validated.
- **Readonly DB**: SQL uses the `stonex_ops_readonly` role, derived from stonx
  config by default; explicit readonly URLs are optional.
- **Timeouts**: PostgreSQL `statement_timeout` and a client-side timeout both
  cap SQL execution.
- **Output redaction**: sensitive JSON keys and SQL columns are filtered before
  returning data to the MCP client.
