---
name: stonex-report-status
description: Check StoneX report generation status (daily, weekly, monthly). Use when the user asks about "报表", "日报", "周报", "月报", "report status", "did the report run", "报表出了吗", or wants to verify report jobs.
---

# StoneX Report Status

Check whether daily, weekly, and monthly reports have been generated and delivered.

## Phase 0: Environment routing

Two MCP servers are available. All tools are prefixed `mcp__stonex-ops-<env>__`.
Pick the target based on the user's words:

| User says | Use MCP server |
|---|---|
| "demo", "测试", "演示", "test" | `stonex-ops-demo` |
| "main", "生产", "正式", "prod", "主" | `stonex-ops-main` |
| "两边", "all", "全部", "都", "两个" | Run **both** |
| No environment mentioned | Ask: "hk-demo or hk-main?" |

## Phase 1: Discover environment and tenants

Call `ops_env_check` to confirm the environment. Then query active tenants:

```sql
SELECT tenant FROM dim.dim_tenant WHERE status = 'active';
```

If the user names a specific tenant, use that. Otherwise report for all active tenants.

## Phase 2: Latest reports

```sql
-- Latest run of each kind, per tenant
SELECT identity, kind, period, status, generated_at, created_at, path
FROM ops.report_run
WHERE (identity, kind, created_at) IN (
  SELECT identity, kind, MAX(created_at) FROM ops.report_run GROUP BY identity, kind
)
ORDER BY identity, kind;

-- Latest release (delivery), per tenant
SELECT identity, kind, period, generated_at, released_at, released_by
FROM ops.report_release
WHERE (identity, kind, period) IN (
  SELECT identity, kind, period FROM (
    SELECT identity, kind, period,
      ROW_NUMBER() OVER (PARTITION BY identity, kind ORDER BY released_at DESC) AS rn
    FROM ops.report_release
  ) sub WHERE rn = 1
)
ORDER BY identity, kind;

-- Recent report-job failures
SELECT job_id, identity, kind, status, last_error_code, last_error_message, created_at
FROM ops.worker_jobs
WHERE kind IN ('daily', 'weekly', 'monthly', 'hub', 'window')
  AND status = 'failed'
  AND created_at > NOW() - INTERVAL '7 days'
ORDER BY created_at DESC
LIMIT 20;
```

## Phase 3: Interpretation

- `report_run.status = 'built'` → report HTML generated at `path`
- `report_release` record exists → delivered to the tenant
- Period missing from `report_run` → schedule didn't fire or job stuck — check `ops.worker_jobs`
- `report_run` present but no `report_release` → generated, not delivered

## Phase 4: Output

```
## Report Status — <env>

| Tenant | Kind | Period | Built | Released | Generated At |
|---|---|---|---|---|---|
| <tenant> | daily | 2026-06-17 | ✅ | ✅ | 2026-06-18 06:23 |
| <tenant> | weekly | ... | ✅ | ❌ | ... |
| <tenant> | monthly | ... | ✅ | ✅ | ... |

### Issues
- <list failures, missing periods, undelivered reports>
```
