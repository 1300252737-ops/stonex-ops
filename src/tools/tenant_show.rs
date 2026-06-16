//! tenant_show:查看单个租户的接入状态和连接信息。

use serde::Serialize;
use std::path::PathBuf;

use crate::executor;
use crate::whitelist::AllowedCommand;

#[derive(Debug, Serialize)]
pub(crate) struct TenantShowResult {
    pub identity: String,
    pub ops_tag: Option<String>,
    pub status: Option<String>,
    pub display_name: Option<String>,
    pub business_timezone: Option<String>,
    pub home_path: Option<String>,
    pub shop: Option<serde_json::Value>,
    pub connections: Vec<serde_json::Value>,
}

pub(crate) async fn run(
    stonx_bin: PathBuf,
    env: &str,
    path: &str,
    tenant: &str,
) -> Result<TenantShowResult, String> {
    let cmd = AllowedCommand::TenantShow {
        tenant: tenant.to_string(),
    };
    let output = executor::execute(stonx_bin, env, path, &cmd)
        .await
        .map_err(|e| format!("tenant show failed: {e}"))?;

    let parsed: serde_json::Value =
        serde_json::from_str(&output.stdout).map_err(|e| format!("parse tenant show json: {e}"))?;

    Ok(TenantShowResult {
        identity: tenant.to_string(),
        ops_tag: parsed.get("ops_tag").and_then(|v| v.as_str()).map(|s| s.to_string()),
        status: parsed.get("status").and_then(|v| v.as_str()).map(|s| s.to_string()),
        display_name: parsed.get("display_name").and_then(|v| v.as_str()).map(|s| s.to_string()),
        business_timezone: parsed.get("business_timezone").and_then(|v| v.as_str()).map(|s| s.to_string()),
        home_path: parsed.get("home_path").and_then(|v| v.as_str()).map(|s| s.to_string()),
        shop: parsed.get("shop").cloned(),
        connections: parsed
            .get("connections")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default(),
    })
}
