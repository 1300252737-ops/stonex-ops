# stonex-ops

独立运维诊断 MCP server,不连接数据库,通过 `stonx ctl --output json` 间接访问系统状态。

## 架构

```
MCP client / agent
  -> stonex-ops MCP server (stdio JSON-RPC)
  -> allowlisted stonx ctl --output json
  -> stonx runtime / DB / provider probes
```

## 关键原则

- 不直连数据库,不依赖 stonex 源码
- 只调用 `stonx ctl ... --output json` 契约
- 命令白名单 + 参数校验 + 审计日志
- 第一阶段只做只读诊断

## 构建

```bash
cargo build --release
```

## 使用

### 本地 (stdio MCP)

```bash
stonex-ops --stonx-bin /path/to/stonx --env test
```

### SSH Remote (生产 HK main)

```bash
ssh -T ops@hk-main /opt/stonex-ops/bin/stonex-ops \
  --stonx-bin /opt/stonx/bin/stonx \
  --env main
```

在 Claude Code 中配置:

```json
{
  "mcpServers": {
    "stonex-ops": {
      "command": "ssh",
      "args": ["-T", "ops@hk-main", "/opt/stonex-ops/bin/stonex-ops", "--stonx-bin", "/opt/stonx/bin/stonx", "--env", "main"]
    }
  }
}
```

### MCP Tools

| Tool | 说明 |
|------|------|
| `env_check` | 自检:stonx 版本、DB 连通性、环境 |
| `tenant_list` | 列出所有租户 |
| `tenant_show` | 查看单个租户接入状态和连接 |
| `probe_connections` | 探测数据连接状态 |
| `worker_jobs` | 查看 worker 作业列表 |
| `worker_schedules` | 查看 worker 调度配置 |

## 审计

每次 tool 调用记录 JSONL 行到 stderr (以及可选的 `--audit-file`):

```json
{"timestamp":"2026-06-16T10:00:00Z","tool":"probe_connections","arguments":{...},"result_status":"success","duration_ms":230,"session_id":"..."}
```

## 安全

- 命令白名单:只能执行预定义的 `stonx ctl` 子命令
- 参数校验:拒绝 shell 元字符
- 无 DB 凭证:不读取或持有数据库密码
- 输出脱敏:JSON 输出中的敏感字段(如 token)由 `stonx ctl` 负责脱敏
