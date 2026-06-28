---
name: stonex-user-query
description: Query ChatBI user activity and usage. Use when the user asks for "用户查询", "问答记录", "活跃用户", "usage", "谁问了问题", "user activity", "提问统计", or wants to see how tenants/users are using the AI.
---

# StoneX User Query

Query AI usage per user/tenant for a date range. Shows question count, session count, and active users.

## Phase 0: Environment routing

Two MCP servers are available. All tools are prefixed `mcp__stonex-ops-<env>__`.

| User says | Use MCP server |
|---|---|
| "demo", "测试", "演示", "test" | `stonex-ops-demo` |
| "main", "生产", "正式", "prod", "主" | `stonex-ops-main` |
| No environment mentioned | Default to `stonex-ops-main` |

## Phase 1: Determine scope

If the user specifies a date range, use that. Otherwise default to today (Asia/Shanghai).

If the user specifies a tenant or user, filter by that. Otherwise show all active tenants.

Call `ops_env_check` first.

## Phase 2: Query usage

**Default: per-user breakdown.** Only use quick count if the user explicitly says "只看总数" or "total only".

### 👤 Per-user breakdown (default)

Single unified SQL with display name and email:

```sql
SELECT u.tenant_id,
  COALESCE(a.display_name, u.subject) AS display_name,
  COALESCE(a.email, '') AS email,
  u.questions, u.last_active
FROM (
  SELECT s.tenant_id, s.subject,
    COUNT(m.id) FILTER (WHERE m.role = 'user') AS questions,
    MAX(s.created_at) AS last_active
  FROM ops.ai_sessions s
  JOIN ops.ai_messages m ON m.session_id = s.id
  WHERE s.created_at >= (<start_date>) AT TIME ZONE 'Asia/Shanghai'
    AND s.created_at < (<end_date> + INTERVAL '1 day') AT TIME ZONE 'Asia/Shanghai'
  GROUP BY s.tenant_id, s.subject
) u
LEFT JOIN LATERAL (
  SELECT s.display_name, li.identifier AS email
  FROM acl.subject s
  LEFT JOIN acl.login_identity li ON li.subject = s.subject AND li.kind = 'email' AND li.status = 'active'
  WHERE s.subject = u.subject
) a ON true
ORDER BY u.tenant_id, u.questions DESC;
```

Note: the `sessions` column hits the MCP read-only redaction regex and returns `[redacted]` — skip it in both query and output.

### 🏃 Quick count (only when user says "总数" / "total")

`ai_tenant_daily_usage` — pre-aggregated, cheapest:

```sql
SELECT tenant_id, usage_date, question_count
FROM ops.ai_tenant_daily_usage
WHERE usage_date >= <start_date>
  AND usage_date <= <end_date>
ORDER BY tenant_id, usage_date;
```

### 🔍 Resolve user identity

When the user asks who a specific subject is (no date range, single lookup):

```sql
SELECT s.subject, s.display_name, s.status,
  li.identifier AS email
FROM acl.subject s
LEFT JOIN acl.login_identity li ON li.subject = s.subject AND li.kind = 'email' AND li.status = 'active'
WHERE s.subject = '<subject>';
```

### 💬 Recent question text

Only run this if the user wants to see what was asked:

```sql
SELECT s.tenant_id, s.subject, m.text, m.created_at
FROM ops.ai_messages m
JOIN ops.ai_sessions s ON s.id = m.session_id
WHERE m.role = 'user'
  AND s.tenant_id IN (SELECT tenant_id FROM dim.dim_tenant WHERE status = 'active')
ORDER BY m.created_at DESC
LIMIT <N>;
```

## Phase 3: Output format

```
用户查询 — <env> @ <date_range>

<tenant>
  <display_name> / <email>   提问 N    最后活跃 <time>
  <display_name> / <email>   提问 N    最后活跃 <time>
  总计 N 提问，N 账号活跃
  每日: <date>=N, <date>=N

---

<tenant>
  ...
```

Always resolve subjects to display_name + email from `acl.subject` / `acl.login_identity`. If a subject has no matching ACL record, fall back to the raw subject string.

If a single user is specified, also show their question list:

```
<user> 提问记录

<datetime>  <question text truncated>
<datetime>  <question text truncated>
```
