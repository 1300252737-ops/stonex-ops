---
name: stonex-connection-diagnostics
description: Diagnose StoneX data source connection problems. Use when the user asks about "连接", "connection", "probe", "数据源", "授权", "auth", "diagnostics", or when probe results show problems that need investigation.
---

# StoneX Connection Diagnostics

Run a targeted connection probe and surface actionable diagnosis.

## Phase 0: Environment routing

Two MCP servers are available. All tools are prefixed `mcp__stonex-ops-hk-<env>__`.
Pick the target based on the user's words:

| User says | Use MCP server |
|---|---|
| "demo", "测试", "演示", "test" | `stonex-ops-hk-demo` |
| "main", "生产", "正式", "prod", "主" | `stonex-ops-hk-main` |
| "两边", "all", "全部", "都", "两个" | Run **both** |
| No environment mentioned | Ask: "hk-demo or hk-main?" |

## Phase 1: Identify environment

Call `ops_env_check`. Record the env name for the report.

## Phase 2: Probes and tenant discovery (parallel)

Run `ops_probe_connections` with no arguments (all tenants). If the probe returns problems, query active tenants in parallel:

```sql
SELECT tenant, status FROM dim.dim_tenant WHERE status = 'active';
```

## Phase 3: Deep-dive (if problems found)

If probe shows `action_required` with `xhs_auth_missing`:

```sql
SELECT tenant, shop_id, status, expires_at, updated_at
FROM ext.xhs_shop_auth
ORDER BY updated_at DESC;
```

If probe shows `action_required` with `jst_auth_missing`:

```sql
SELECT tenant, sys, status, expires_at
FROM ext.auth
WHERE sys = 'jst'
ORDER BY created_at DESC;
```

If probe shows `freshness_lagging`:

```sql
SELECT job_id, tenant, shop_id, watermark_key, watermark_value, updated_at
FROM ops.job_watermarks
ORDER BY tenant, shop_id, watermark_key;
```

If data sync looks stale:

```sql
SELECT identity, kind, status, period_start, period_end, created_at
FROM ops.ingest_runs
ORDER BY created_at DESC
LIMIT 20;
```

No fixed output format. Present problems by severity with analysis + suggested action. Skip healthy entries. Use Chinese.