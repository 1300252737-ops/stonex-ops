//! tenant_list:列出所有租户的概览信息。
//!
//! 返回每个租户的 identity、ops_tag、状态和连接状态。

use serde::Serialize;
use std::path::PathBuf;

use crate::executor;
use crate::whitelist::AllowedCommand;

#[derive(Debug, Serialize)]
pub(crate) struct TenantListResult {
    pub tenants: Vec<serde_json::Value>,
}

pub(crate) async fn run(
    stonx_bin: PathBuf,
    env: &str,
    path: &str,
) -> Result<TenantListResult, String> {
    let cmd = AllowedCommand::TenantList;
    let output = executor::execute(stonx_bin, env, path, &cmd)
        .await
        .map_err(|e| format!("tenant list failed: {e}"))?;

    let tenants: Vec<serde_json::Value> = serde_json::from_str(&output.stdout)
        .map_err(|e| format!("parse tenant list json: {e}"))?;

    Ok(TenantListResult { tenants })
}
