"""stonex-ops: standalone ops diagnostics tool.

Two-layer boundary:

    MCP client / agent
      -> stonex-ops mcp (stdio JSON-RPC)
      -> readonly PostgreSQL schema/SQL tools
      -> allowlisted stonx ctl probe for active connection checks

Key principles:
- No dependency on stonex source.
- No query registry; callers write SQL after inspecting schema.
- PostgreSQL readonly role, DB timeout, client timeout, and output redaction are
  the SQL safety boundary.
- Audit log every MCP tool call.
- Read-only diagnostics plus one explicit active probe boundary.

Probe boundary: only `ops_probe_connections` triggers
`stonx ctl probe`, which may record `ops.connection_probe_state`
through stonx. All other tools are strictly read-only.
"""

__version__ = "0.1.0"
