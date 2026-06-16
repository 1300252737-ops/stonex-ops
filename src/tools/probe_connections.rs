//! probe_connections:探测一个租户(或所有租户)的数据连接状态。
//!
//! 支持的 probe 类型:
//! - all:所有连接 (xhs-api, jst/wangdian, runtime, freshness)
//! - xhs-api:小红书 API 连接
//! - jst:JST ERP 连接
//! - wangdian:旺店通 ERP 连接
//! - runtime:运行时健康
//! - freshness:数据新鲜度

use serde::Serialize;
use std::path::PathBuf;

use crate::executor;
use crate::whitelist::AllowedCommand;

#[derive(Debug, Serialize)]
pub(crate) struct ProbeConnectionsResult {
    pub scope: Option<ProbeScope>,
    pub result: Option<String>,
    pub checks: Option<usize>,
    pub problems: Option<usize>,
    pub connections: Vec<serde_json::Value>,
}

#[derive(Debug, Serialize)]
pub(crate) struct ProbeScope {
    pub tenant: Option<String>,
    pub shop: Option<String>,
}

pub(crate) async fn run(
    stonx_bin: PathBuf,
    env: &str,
    path: &str,
    tenant: Option<&str>,
    shop_id: Option<&str>,
) -> Result<ProbeConnectionsResult, String> {
    let cmd = match tenant {
        Some(tenant) => AllowedCommand::Probe {
            tenant: Some(tenant.to_string()),
            shop_id: shop_id.map(|s| s.to_string()),
        },
        None => AllowedCommand::ProbeAll,
    };

    let output = executor::execute(stonx_bin, env, path, &cmd)
        .await
        .map_err(|e| format!("probe failed: {e}"))?;

    let parsed: serde_json::Value =
        serde_json::from_str(&output.stdout).map_err(|e| format!("parse probe json: {e}"))?;

    // 收集所有 scope 的 connections
    let mut all_connections = Vec::new();
    if let Some(scopes) = parsed.get("scopes").and_then(|v| v.as_array()) {
        for scope in scopes {
            if let Some(conns) = scope.get("connections").and_then(|v| v.as_array()) {
                for conn in conns {
                    let mut entry = conn.clone();
                    // 注入 scope 信息
                    if let Some(obj) = entry.as_object_mut() {
                        if let (Some(tenant), Some(shop)) = (
                            scope.get("tenant").and_then(|v| v.as_str()),
                            scope.get("shop").and_then(|v| v.as_str()),
                        ) {
                            obj.insert("tenant".to_string(), serde_json::json!(tenant));
                            obj.insert("shop".to_string(), serde_json::json!(shop));
                        }
                    }
                    all_connections.push(entry);
                }
            }
        }
    }

    Ok(ProbeConnectionsResult {
        scope: tenant.map(|t| ProbeScope {
            tenant: Some(t.to_string()),
            shop: shop_id.map(|s| s.to_string()),
        }),
        result: parsed.get("result").and_then(|v| v.as_str()).map(|s| s.to_string()),
        checks: parsed.get("checks").and_then(|v| v.as_u64()).map(|v| v as usize),
        problems: parsed.get("problems").and_then(|v| v.as_u64()).map(|v| v as usize),
        connections: all_connections,
    })
}
