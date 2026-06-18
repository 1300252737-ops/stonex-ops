---
name: stonex-user-query
description: Query ChatBI user activity and usage. Use when the user asks for "用户查询", "问答记录", "活跃用户", "usage", "谁问了问题", "user activity", "提问统计", or wants to see how tenants/users are using the AI.
---

# StoneX User Query

Query AI usage per user/tenant for a date range. Shows question count, session count, and active users.

## Phase 0: Environment routing

Two MCP servers are available. All tools are prefixed `mcp__stonex-ops-hk-<env>__`.

| User says | Use MCP server |
|---|---|
| "demo", "测试", "演示", "test" | `stonex-ops-hk-demo` |
| "main", "生产", "正式", "prod", "主" | `stonex-ops-hk-main` |
| No environment mentioned | Ask |

## Phase 1: Determine scope

If the user specifies a date range, use that. Otherwise default to yesterday (Asia/Shanghai).

If the user specifies a tenant or user, filter by that. Otherwise show all active tenants.

Call `ops_env_check` first. Then query active tenants:

```sql
SELECT tenant_id FROM dim.dim_tenant WHERE status = 'active';
```

## Phase 2: Query usage

### Per-user breakdown for date range

```sql
SELECT s.tenant_id, s.subject,
  COUNT(DISTINCT s.id) AS sessions,
  COUNT(m.id) FILTER (WHERE m.role = 'user') AS questions,
  MAX(s.created_at) AS last_active
FROM ops.ai_sessions s
JOIN ops.ai_messages m ON m.session_id = s.id
WHERE s.tenant_id IN (SELECT tenant_id FROM dim.dim_tenant WHERE status = 'active')
  AND s.created_at >= <start_date> AT TIME ZONE 'Asia/Shanghai'
  AND s.created_at < (<end_date> + INTERVAL '1 day') AT TIME ZONE 'Asia/Shanghai'
GROUP BY s.tenant_id, s.subject
ORDER BY s.tenant_id, questions DESC;
```

Replace `<start_date>` and `<end_date>` with the user's requested range, or default to yesterday.

### Resolve user identity

When the user asks who a specific subject is, or when the output should show names instead of raw subject IDs, join against the ACL schema:

```sql
SELECT s.subject, s.display_name, s.status,
  li.identifier AS email
FROM acl.subject s
LEFT JOIN acl.login_identity li ON li.subject = s.subject AND li.kind = 'email' AND li.status = 'active'
WHERE s.subject = '<subject>';
```

Wrap this into the per-user breakdown when display names are wanted:

```sql
SELECT u.tenant_id, u.subject,
  a.display_name, a.email,
  u.sessions, u.questions, u.last_active
FROM (
  ...per-user subquery above...
) u
LEFT JOIN LATERAL (
  SELECT s.display_name, li.identifier AS email
  FROM acl.subject s
  LEFT JOIN acl.login_identity li ON li.subject = s.subject AND li.kind = 'email' AND li.status = 'active'
  WHERE s.subject = u.subject
) a ON true
ORDER BY u.tenant_id, u.questions DESC;
```

### Aggregate daily totals

```sql
SELECT tenant_id, usage_date, question_count
FROM ops.ai_tenant_daily_usage
WHERE tenant_id IN (SELECT tenant_id FROM dim.dim_tenant WHERE status = 'active')
  AND usage_date >= <start_date>
  AND usage_date <= <end_date>
ORDER BY tenant_id, usage_date;
```

### Recent question text (last N questions across all users)

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
  <display_name> / <email>   提问 N    会话 N    最后活跃 <time>
  <display_name> / <email>   提问 N    会话 N    最后活跃 <time>
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
