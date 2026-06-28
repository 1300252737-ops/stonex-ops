---
name: stonex-daily-report
description: Generate a concise daily ops report for StoneX. Use when the user asks for "每日报告", "日报", "daily report", "今日情况", "今天怎么样", "ops daily", or wants a daily summary of platform health. Reports delta (what changed today) rather than full snapshots.
---

# StoneX Daily Ops Report

Two sections: **基础信息** (per-tenant summary) + **异常** (only what needs attention).

## Phase 0: Environment routing

Two MCP servers are available. All tools are prefixed `mcp__stonex-ops-<env>__`.

| User says | Use MCP server |
|---|---|
| "demo", "测试", "演示", "test" | `stonex-ops-demo` |
| "main", "生产", "正式", "prod", "主" | `stonex-ops-main` |
| "两边", "all", "全部", "都", "两个" | Run both, side-by-side |
| No environment mentioned | Ask |

## Phase 1: Identify environment

Call `ops_env_check`. Record `env` and `stonx_version`.

## Phase 2: Gather data (parallel)

Run `ops_probe_connections`, website curl checks, and these SQL queries in parallel.

### Website health

Use `curl -sL -o /dev/null -w "%{http_code}" <url>` to check the StoneX website. Map by environment:

| env | URL |
|---|---|
| main | `https://stonex.yuece.tech/` |
| demo | `https://stonex-demo.yuece.tech/` |

Run the matching curl command. Record HTTP status code and response time.

### Active tenants

```sql
SELECT tenant_id, ops_tag FROM dim.dim_tenant WHERE status = 'active';
```

### Reports — latest build per tenant per kind

```sql
SELECT identity, kind, period, status, created_at
FROM (
  SELECT identity, kind, period, status, created_at,
    ROW_NUMBER() OVER (PARTITION BY identity, kind ORDER BY period DESC, created_at DESC) AS rn
  FROM ops.report_run
  WHERE identity IN (SELECT tenant_id FROM dim.dim_tenant WHERE status = 'active')
) sub
WHERE rn = 1
ORDER BY identity, kind;
```

### Worker jobs — report_daily (last 48h, to see attempts + retries)

```sql
SELECT job_id, identity, shop_id, status, attempt_count, last_error_code, created_at, finished_at
FROM ops.worker_jobs
WHERE identity IN (SELECT tenant_id FROM dim.dim_tenant WHERE status = 'active')
  AND kind = 'report_daily'
  AND created_at > NOW() - INTERVAL '48 hours'
ORDER BY identity, shop_id, created_at;
```

### Connection probe state — non-ok for active tenants

```sql
SELECT cps.tenant_id, cps.connection_id, cps.status, cps.reason_code, cps.last_success_at
FROM ops.connection_probe_state cps
JOIN dim.dim_tenant dt ON dt.tenant_id = cps.tenant_id AND dt.status = 'active'
WHERE cps.status != 'ok';
```

### AI usage — yesterday, per user (resolved to display_name + email)

```sql
SELECT u.tenant_id, u.subject,
  a.display_name, a.email,
  u.sessions, u.questions
FROM (
  SELECT s.tenant_id, s.subject,
    COUNT(DISTINCT s.id) AS sessions,
    COUNT(m.id) FILTER (WHERE m.role = 'user') AS questions
  FROM ops.ai_sessions s
  JOIN ops.ai_messages m ON m.session_id = s.id
  WHERE s.tenant_id IN (SELECT tenant_id FROM dim.dim_tenant WHERE status = 'active')
    AND s.created_at >= (CURRENT_DATE - INTERVAL '1 day')::timestamp AT TIME ZONE 'Asia/Shanghai'
    AND s.created_at < CURRENT_DATE::timestamp AT TIME ZONE 'Asia/Shanghai'
  GROUP BY s.tenant_id, s.subject
) u
LEFT JOIN LATERAL (
  SELECT s.display_name, li.identifier AS email
  FROM acl.subject s
  LEFT JOIN acl.login_identity li ON li.subject = s.subject AND li.kind = 'email' AND li.status = 'active'
  WHERE s.subject = u.subject
) a ON true
ORDER BY u.tenant_id, u.questions DESC;

SELECT tenant_id, question_count
FROM ops.ai_tenant_daily_usage
WHERE tenant_id IN (SELECT tenant_id FROM dim.dim_tenant WHERE status = 'active')
  AND usage_date = CURRENT_DATE - INTERVAL '1 day';
```

## Phase 3: Analysis

**Business date:** Daily fires at 06:00 CST for the previous day.

**Per tenant, determine:**
- Did the daily report build for the expected period? Check `report_run`.
- Did the build involve retries? Check `worker_jobs` — if the first attempt failed but a later retry succeeded, the report is OK but note the delay.
- Are any connections unhealthy? Duration from `connection_probe_state`.
- What's the AI usage for yesterday?

**What goes into the report:**

基础信息 section:
- Per tenant, per report kind: period, status, retry info if any.
- Yesterday's AI usage: total questions + per-user breakdown.
- Website: URL, HTTP status, response time. Only mention if not 200.

异常 section:
- Connection problems from `connection_probe_state` (non-ok, active tenant).
- Worker jobs that failed in the last 24 hours with no successful retry.
- If a job failed but a later retry succeeded, note the delay in 基础信息, not here.
- Chronic issues: show duration in days.

**Never list healthy things.** If a connection is ok, don't mention it. If reports are all fine, just say the period. No "数据源" section.

**Exclude — dynamic only:**
- Tenants NOT in `dim.dim_tenant WHERE status = 'active'` (already scoped above).
- Abandoned pipelines: domains with zero ingest runs in the last 7 days.

```sql
SELECT source, domain
FROM ops.ingest_runs
WHERE started_at > NOW() - INTERVAL '7 days'
GROUP BY source, domain
HAVING COUNT(*) = 0;
```

No fixed output format. Use conversational Chinese, organize by tenant. Split into 基础信息 (reports, AI usage, website) and 异常 (problems needing attention). Only mention problems, skip healthy items.
