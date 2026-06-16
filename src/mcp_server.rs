//! MCP server 实现:基于 rmcp 框架的 stdio MCP server。
//!
//! 与 stonex-mcp 的关键区别:
//! - 不连接 DB,不依赖 stonex crate
//! - 工具通过调用 `stonx ctl ... --output json` 实现
//! - 命令白名单 + 参数校验 + 审计日志 + 输出脱敏

use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::Context;
use rmcp::handler::server::ServerHandler;
use rmcp::model::{
    CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams,
    ServerCapabilities, ServerInfo, Tool, ToolAnnotations,
};
use rmcp::service::RequestContext;
use rmcp::{ErrorData as McpError, RoleServer, ServiceExt};
use serde_json::{Value, json};
use tokio::sync::Semaphore;

use crate::audit::{AuditEntry, AuditLogger, AuditStatus};
use crate::redaction;
use crate::tools;

/// 最大并发 tool 调用数。
const MAX_CONCURRENT_CALLS: usize = 3;

fn make_tool(name: &str, description: &str, input_schema: Value) -> Tool {
    Tool::new(
        name.to_string(),
        description.to_string(),
        Arc::new(input_schema.as_object().cloned().unwrap_or_default()),
    )
    .with_annotations(
        ToolAnnotations::new()
            .read_only(true)
            .destructive(false)
            .idempotent(true)
            .open_world(false),
    )
}

fn tool_definitions() -> Vec<Tool> {
    vec![
        make_tool(
            "ops_env_check",
            "自检 stonex-ops 能否正常工作:stonx 版本、DB 连通性、环境信息。",
            json!({"type":"object","properties":{},"additionalProperties":false}),
        ),
        make_tool(
            "ops_tenant_list",
            "列出所有租户的概览信息:identity、状态、数据连接状态。",
            json!({"type":"object","properties":{},"additionalProperties":false}),
        ),
        make_tool(
            "ops_tenant_show",
            "查看一个租户的详细接入状态:基本属性、店铺范围、数据连接和鉴权状态。",
            json!({
                "type":"object",
                "properties":{
                    "tenant":{"type":"string","description":"系统生成的租户 identity"}
                },
                "required":["tenant"],
                "additionalProperties":false
            }),
        ),
        make_tool(
            "ops_probe_connections",
            "探测租户(或所有租户)的数据连接状态:小红书 API、ERP、运行时和数据新鲜度。",
            json!({
                "type":"object",
                "properties":{
                    "tenant":{"type":"string","description":"可选,租户 identity。不传则探测所有 active 租户"},
                    "shop_id":{"type":"string","description":"可选,指定店铺。不传则探测所有 active 店铺"}
                },
                "additionalProperties":false
            }),
        ),
        make_tool(
            "ops_data_freshness",
            "查看租户数据新鲜度:各店铺最新数据日期和过期状态。",
            json!({
                "type":"object",
                "properties":{
                    "tenant":{"type":"string","description":"可选,租户 identity。不传则查看所有"}
                },
                "additionalProperties":false
            }),
        ),
        make_tool(
            "ops_worker_jobs",
            "查看 worker 作业列表:排队/运行/完成/失败状态的日报、周报后台作业。",
            json!({
                "type":"object",
                "properties":{
                    "tenant":{"type":"string","description":"可选,按租户过滤"},
                    "status":{"type":"string","enum":["queued","running","succeeded","failed","cancelled"],"description":"可选,按状态过滤"},
                    "limit":{"type":"integer","minimum":1,"maximum":500,"description":"可选,最大返回条数(默认50)"}
                },
                "additionalProperties":false
            }),
        ),
        make_tool(
            "ops_worker_schedules",
            "查看 worker 调度配置:cron 表达式、状态(active/paused)、时区。",
            json!({
                "type":"object",
                "properties":{
                    "tenant":{"type":"string","description":"可选,按租户过滤"}
                },
                "additionalProperties":false
            }),
        ),
        make_tool(
            "ops_report_status",
            "查看最近报表生成状态:最新成功的日报/周报及最近作业列表。",
            json!({
                "type":"object",
                "properties":{
                    "tenant":{"type":"string","description":"可选,按租户过滤"}
                },
                "additionalProperties":false
            }),
        ),
    ]
}

#[derive(Clone)]
pub(crate) struct OpsMcpState {
    pub stonx_bin: PathBuf,
    pub env: String,
    pub path: String,
    pub logger: Arc<AuditLogger>,
    pub concurrency: Arc<Semaphore>,
}

#[derive(Clone)]
struct OpsMcp {
    state: Arc<OpsMcpState>,
}

impl ServerHandler for OpsMcp {
    fn get_info(&self) -> ServerInfo {
        let mut info = ServerInfo::default();
        info.instructions = Some(
            "StoneX 运维诊断工具 (stonex-ops):查看租户接入、连接状态、数据新鲜度、worker 作业和调度、报表状态。\
            只读、不直连数据库、审计记录每次调用。"
                .into(),
        );
        info.capabilities = ServerCapabilities::builder().enable_tools().build();
        info
    }

    async fn list_tools(
        &self,
        _req: Option<PaginatedRequestParams>,
        _ctx: RequestContext<RoleServer>,
    ) -> Result<ListToolsResult, McpError> {
        Ok(ListToolsResult {
            tools: tool_definitions(),
            next_cursor: None,
            meta: None,
        })
    }

    async fn call_tool(
        &self,
        req: CallToolRequestParams,
        _ctx: RequestContext<RoleServer>,
    ) -> Result<CallToolResult, McpError> {
        let args = req
            .arguments
            .map(Value::Object)
            .unwrap_or_else(|| json!({}));

        // 并发限制
        let _permit = match self.state.concurrency.try_acquire() {
            Ok(permit) => permit,
            Err(_) => {
                return Ok(CallToolResult::structured_error(json!({
                    "code": "too_many_requests",
                    "message": format!(
                        "并发请求过多,最多同时 {} 个工具调用。请稍后重试。",
                        MAX_CONCURRENT_CALLS
                    )
                })));
            }
        };

        let started = std::time::Instant::now();
        let result = execute_tool(&self.state, req.name.as_ref(), &args).await;
        let duration_ms = started.elapsed().as_millis() as i64;

        let (status, error_msg) = match &result {
            Ok(value) if value.is_error == Some(true) => {
                (AuditStatus::ExecutionFailed, Some("tool returned error".to_string()))
            }
            Ok(_) => (AuditStatus::Success, None),
            Err(err) => (AuditStatus::ExecutionFailed, Some(err.to_string())),
        };

        self.state.logger.log(AuditEntry {
            timestamp: chrono::Utc::now().to_rfc3339(),
            tool: req.name.to_string(),
            arguments: args,
            result_status: status,
            error: error_msg,
            duration_ms,
            session_id: self.state.logger.session_id().to_string(),
        });

        result
    }
}

fn mcp_err(msg: impl Into<String>) -> McpError {
    McpError::internal_error(msg.into(), None)
}

async fn execute_tool(
    state: &OpsMcpState,
    name: &str,
    args: &Value,
) -> Result<CallToolResult, McpError> {
    let bin = &state.stonx_bin;
    let env = state.env.as_str();
    let path = state.path.as_str();

    let mut result: Result<Value, McpError> = match name {
        "ops_env_check" => {
            let data = tools::env_check::run(bin.to_path_buf(), env, path)
                .await
                .map_err(|e| mcp_err(e))?;
            Ok(serde_json::to_value(data).unwrap_or(json!({"error":"serialize"})))
        }
        "ops_tenant_list" => {
            let data = tools::tenant_list::run(bin.to_path_buf(), env, path)
                .await
                .map_err(|e| mcp_err(e))?;
            Ok(serde_json::to_value(data).unwrap_or(json!({"error":"serialize"})))
        }
        "ops_tenant_show" => {
            let tenant = require_string(args, "tenant")?;
            let data =
                tools::tenant_show::run(bin.to_path_buf(), env, path, &tenant)
                    .await
                    .map_err(|e| mcp_err(e))?;
            Ok(serde_json::to_value(data).unwrap_or(json!({"error":"serialize"})))
        }
        "ops_probe_connections" => {
            let tenant = optional_string(args, "tenant");
            let shop_id = optional_string(args, "shop_id");
            let data = tools::probe_connections::run(
                bin.to_path_buf(),
                env,
                path,
                tenant.as_deref(),
                shop_id.as_deref(),
            )
            .await
            .map_err(|e| mcp_err(e))?;
            Ok(serde_json::to_value(data).unwrap_or(json!({"error":"serialize"})))
        }
        "ops_data_freshness" => {
            let tenant = optional_string(args, "tenant");
            let data = tools::data_freshness::run(
                bin.to_path_buf(),
                env,
                path,
                tenant.as_deref(),
            )
            .await
            .map_err(|e| mcp_err(e))?;
            Ok(serde_json::to_value(data).unwrap_or(json!({"error":"serialize"})))
        }
        "ops_worker_jobs" => {
            let tenant = optional_string(args, "tenant");
            let status = optional_string(args, "status");
            let limit = args.get("limit").and_then(|v| v.as_i64());
            let data = tools::worker_jobs::run(
                bin.to_path_buf(),
                env,
                path,
                tenant.as_deref(),
                status.as_deref(),
                limit,
            )
            .await
            .map_err(|e| mcp_err(e))?;
            Ok(serde_json::to_value(data).unwrap_or(json!({"error":"serialize"})))
        }
        "ops_worker_schedules" => {
            let tenant = optional_string(args, "tenant");
            let data = tools::worker_schedules::run(
                bin.to_path_buf(),
                env,
                path,
                tenant.as_deref(),
            )
            .await
            .map_err(|e| mcp_err(e))?;
            Ok(serde_json::to_value(data).unwrap_or(json!({"error":"serialize"})))
        }
        "ops_report_status" => {
            let tenant = optional_string(args, "tenant");
            let data = tools::report_status::run(
                bin.to_path_buf(),
                env,
                path,
                tenant.as_deref(),
            )
            .await
            .map_err(|e| mcp_err(e))?;
            Ok(serde_json::to_value(data).unwrap_or(json!({"error":"serialize"})))
        }
        other => Err(mcp_err(format!("unknown tool: {other}"))),
    };

    // 输出脱敏
    if let Ok(ref mut value) = result {
        redaction::redact(value);
    }

    match result {
        Ok(value) => Ok(CallToolResult::structured(value)),
        Err(err) => Ok(CallToolResult::structured_error(json!({
            "code": "execution_failed",
            "message": err.to_string(),
        }))),
    }
}

fn require_string(args: &Value, key: &str) -> Result<String, McpError> {
    args.get(key)
        .and_then(|v| v.as_str())
        .filter(|v| !v.trim().is_empty())
        .map(|v| v.to_string())
        .ok_or_else(|| McpError::invalid_params(format!("missing required argument: {key}"), None))
}

fn optional_string(args: &Value, key: &str) -> Option<String> {
    args.get(key)
        .and_then(|v| v.as_str())
        .filter(|v| !v.trim().is_empty())
        .map(|v| v.to_string())
}

/// 启动 MCP server (stdio JSON-RPC)。
pub(crate) async fn run(
    stonx_bin: PathBuf,
    env: &str,
    path: &str,
    audit_file: Option<&Path>,
) -> anyhow::Result<()> {
    let logger = Arc::new(AuditLogger::new(audit_file)?);

    // 启动时自检
    let check = tools::env_check::run(stonx_bin.clone(), env, path).await;
    match &check {
        Ok(result) => {
            eprintln!(
                "startup check: stonx_reachable={} db_reachable={:?} version={:?}",
                result.stonx_reachable, result.database_reachable, result.stonx_version
            );
        }
        Err(err) => {
            eprintln!("startup check warning: {err}");
        }
    }

    let state = Arc::new(OpsMcpState {
        stonx_bin,
        env: env.to_string(),
        path: path.to_string(),
        logger,
        concurrency: Arc::new(Semaphore::new(MAX_CONCURRENT_CALLS)),
    });

    let service = OpsMcp { state }
        .serve((tokio::io::stdin(), tokio::io::stdout()))
        .await
        .context("stonex-ops MCP server failed")?;

    service.waiting().await?;
    Ok(())
}
