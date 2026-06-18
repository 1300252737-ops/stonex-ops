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
SELECT s.tenant_id, s.user_id,
  COUNT(DISTINCT s.id) AS sessions,
  COUNT(m.id) FILTER (WHERE m.role = 'user') AS questions,
  MAX(s.created_at) AS last_active
FROM ops.ai_sessions s
JOIN ops.ai_messages m ON m.session_id = s.id
WHERE s.tenant_id IN (SELECT tenant_id FROM dim.dim_tenant WHERE status = 'active')
  AND s.created_at >= <start_date> AT TIME ZONE 'Asia/Shanghai'
  AND s.created_at < (<end_date> + INTERVAL '1 day') AT TIME ZONE 'Asia/Shanghai'
GROUP BY s.tenant_id, s.user_id
ORDER BY s.tenant_id, questions DESC;
```

Replace `<start_date>` and `<end_date>` with the user's requested range, or default to yesterday.

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
SELECT s.tenant_id, s.user_id, m.text, m.created_at
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
  <user>          提问 N    会话 N    最后活跃 <time>
  <user>          提问 N    会话 N    最后活跃 <time>
  总计 N 提问，N 账号活跃
  每日: <date>=N, <date>=N

---

<tenant>
  ...
```

If a single user is specified, also show their question list:

```
<user> 提问记录

<datetime>  <question text truncated>
<datetime>  <question text truncated>
```
