---
name: stonex-health-check
description: Run a full StoneX ops health inspection. Use when the user asks for "健康检查", "巡检", "health check", "全面检查", "all checks", "system status", or wants an overview of the StoneX platform. Produces a structured report covering infrastructure, data sources, reports, and schedules.
---

# StoneX Health Check

Run a complete ops inspection and output a structured report.

## Phase 0: Environment routing

Two MCP servers are available. All tools are prefixed `mcp__stonex-ops-hk-<env>__`.
Pick the target based on the user's words:

| User says | Use MCP server |
|---|---|
| "demo", "测试", "演示", "test" | `stonex-ops-hk-demo` |
| "main", "生产", "正式", "prod", "主" | `stonex-ops-hk-main` |
| "两边", "all", "全部", "都", "两个" | Run **both**, produce side-by-side reports |
| No environment mentioned | Ask: "hk-demo or hk-main?" |

## Phase 1: Identify environment (sequential, must run first)

Call `ops_env_check` first to confirm the environment (`test` for demo, `main` for main).
Record the `env` and `stonx_version` fields. Use in report title.

## Phase 2: Gather data (parallel)

Run these **in parallel** — they are independent:

| Tool | Purpose |
|---|---|
| `ops_probe_connections` | All 8 connection probes (no scope = all tenants) |
| `ops_sql_readonly` | Active tenants, report status, worker health |

### SQL to run alongside probes

```sql
-- Active tenants
SELECT tenant, status, ops_tag, created_at FROM dim.dim_tenant WHERE status = 'active' ORDER BY tenant;

-- Latest report of each kind, per tenant
SELECT identity, kind, period, status, created_at
FROM ops.report_run r1
WHERE (identity, kind, created_at) IN (
  SELECT identity, kind, MAX(created_at) FROM ops.report_run GROUP BY identity, kind
)
ORDER BY identity, kind;

-- Failed or stuck jobs in last 3 days
SELECT job_id, identity, kind, status, last_error_message, created_at
FROM ops.worker_jobs
WHERE created_at > NOW() - INTERVAL '3 days'
  AND status IN ('failed', 'cancelled')
ORDER BY created_at DESC
LIMIT 10;

-- Active schedules
SELECT schedule_id, kind, status, cron, timezone FROM ops.worker_schedules WHERE status = 'active' ORDER BY kind;
```

No fixed output format. Present findings grouped by severity (problems first). Use Chinese.