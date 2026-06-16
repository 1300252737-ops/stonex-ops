# stonex-ops

Standalone ops diagnostics MCP server. Does **not** connect to the database.
All data access goes through `stonx ctl --output json`.

## Architecture

```
MCP client / agent
  -> stonex-ops MCP server (stdio JSON-RPC)
  -> allowlisted stonx ctl --output json
  -> stonx runtime / DB / provider probes
```

## Key principles

- No direct database connection, no dependency on stonex source.
- Only calls `stonx ctl ... --output json` contracts.
- Command allowlist + input validation + audit log + output redaction.
- First phase: read-only status tools plus one explicit active probe tool.

## Probe boundary

Only `ops_probe_connections` triggers `stonx ctl probe`, which may write
`ops.connection_probe_state` **through stonx** (stonex-ops itself never
connects to the database). No other tool starts a probe: not at server
startup, not from `ops_env_check`, not from any "freshness" or "status"
tool.

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
ssh -T ops@hk-main /opt/stonex-ops/bin/stonex-ops mcp \
  --stonx-bin /opt/stonx/bin/stonx \
  --env main
```

Claude Code MCP config:

```json
{
  "mcpServers": {
    "stonex-ops": {
      "command": "ssh",
      "args": [
        "-T", "ops@hk-main",
        "/opt/stonex-ops/bin/stonex-ops", "mcp",
        "--stonx-bin", "/opt/stonx/bin/stonx",
        "--env", "main"
      ]
    }
  }
}
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `ops_env_check` | Verify stonx binary reachable, show version. Does NOT run probe. |
| `ops_tenant_list` | List all tenants with identity/status/connection summary. |
| `ops_tenant_show` | Show a tenant's detailed onboarding and connection state. |
| `ops_probe_connections` | Run connection probes (may write probe state through stonx). |
| `ops_worker_jobs` | List worker jobs (queued/running/succeeded/failed/cancelled). |
| `ops_worker_schedules` | List worker schedule configurations. |
| `ops_report_status` | Show recent daily/weekly report generation status. |

## Audit

Every tool call is recorded as a JSONL line to stderr (and an optional
`--audit-file`):

```json
{"timestamp":"2026-06-16T10:00:00Z","tool":"ops_probe_connections","arguments":{...},"result_status":"success","duration_ms":230,"session_id":"..."}
```

## Testing

```bash
pytest
```

## Security

- **Command allowlist**: only predefined `stonx ctl` subcommands.
- **Input validation**: shell metacharacters rejected.
- **No DB credentials**: never reads or holds database passwords.
- **Output redaction**: sensitive fields (tokens, secrets, etc.) filtered.
