//! ops_data_freshness:检查租户数据新鲜度。
//!
//! 通过 probe freshness 结果提取各 shop 的最新数据日期和过期状态。

use serde::Serialize;
use std::path::PathBuf;

use crate::executor;
use crate::whitelist::AllowedCommand;

#[derive(Debug, Serialize)]
pub(crate) struct DataFreshnessResult {
    pub tenant: Option<String>,
    pub shops: Vec<ShopFreshness>,
}

#[derive(Debug, Serialize)]
pub(crate) struct ShopFreshness {
    pub shop_id: String,
    pub tenant: String,
    pub status: String,
    pub message: String,
    pub reason_code: String,
}

pub(crate) async fn run(
    stonx_bin: PathBuf,
    env: &str,
    path: &str,
    tenant: Option<&str>,
) -> Result<DataFreshnessResult, String> {
    let cmd = AllowedCommand::Probe {
        tenant: tenant.map(|t| t.to_string()),
        shop_id: None,
    };

    let output = executor::execute(stonx_bin, env, path, &cmd)
        .await
        .map_err(|e| format!("probe for freshness failed: {e}"))?;

    let parsed: serde_json::Value =
        serde_json::from_str(&output.stdout).map_err(|e| format!("parse probe json: {e}"))?;

    // 从 probe 结果中只提取 freshness 相关的 connection
    let mut shops = Vec::new();
    if let Some(scopes) = parsed.get("scopes").and_then(|v| v.as_array()) {
        for scope in scopes {
            let tenant_id = scope
                .get("tenant")
                .and_then(|v| v.as_str())
                .unwrap_or("-");
            if let Some(connections) = scope.get("connections").and_then(|v| v.as_array()) {
                for conn in connections {
                    let conn_id = conn
                        .get("connection_id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("");
                    if conn_id == "freshness" {
                        let shop_id = scope
                            .get("shop")
                            .and_then(|v| v.as_str())
                            .unwrap_or("-");
                        shops.push(ShopFreshness {
                            shop_id: shop_id.to_string(),
                            tenant: tenant_id.to_string(),
                            status: conn
                                .get("status")
                                .and_then(|v| v.as_str())
                                .unwrap_or("unknown")
                                .to_string(),
                            message: conn
                                .get("message")
                                .and_then(|v| v.as_str())
                                .unwrap_or("")
                                .to_string(),
                            reason_code: conn
                                .get("reason_code")
                                .and_then(|v| v.as_str())
                                .unwrap_or("")
                                .to_string(),
                        });
                    }
                }
            }
        }
    }

    Ok(DataFreshnessResult {
        tenant: tenant.map(|t| t.to_string()),
        shops,
    })
}
