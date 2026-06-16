"""stonex-ops: standalone ops diagnostics tool.

Two-layer boundary:

    MCP client / agent
      -> stonex-ops mcp (stdio JSON-RPC)
      -> allowlisted stonx ctl ... --output json
      -> stonx runtime / DB / provider probes

Key principles:
- No direct database connection, no dependency on stonex source.
- Only calls `stonx ctl ... --output json` contracts.
- Command allowlist + input validation + audit log + output redaction.
- Read-only diagnostics plus one explicit active probe boundary.

Probe boundary: only `ops_probe_connections` triggers
`stonx ctl probe`, which may record `ops.connection_probe_state`
through stonx. All other tools are strictly read-only.
"""

__version__ = "0.1.0"
