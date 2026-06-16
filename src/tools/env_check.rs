//! env_check:自检 stonex-ops 能否正常工作。
//!
//! 无参数,返回:
//! - 当前环境
//! - stonx 版本
//! - stonx 是否可达
//! - DB 连通性(通过 probe 间接检查)

use serde::Serialize;
use std::path::PathBuf;

use crate::executor;
use crate::whitelist::AllowedCommand;

#[derive(Debug, Serialize)]
pub(crate) struct EnvCheckResult {
    pub env: String,
    pub stonx_version: Option<String>,
    pub stonx_reachable: bool,
    pub database_reachable: Option<bool>,
    pub probe_error: Option<String>,
}

pub(crate) async fn run(
    stonx_bin: PathBuf,
    env: &str,
    path: &str,
) -> Result<EnvCheckResult, String> {
    let mut result = EnvCheckResult {
        env: env.to_string(),
        stonx_version: None,
        stonx_reachable: false,
        database_reachable: None,
        probe_error: None,
    };

    // 1. 检查 stonx --version
    match executor::execute(
        stonx_bin.clone(),
        env,
        path,
        &AllowedCommand::StonxVersion,
    )
    .await
    {
        Ok(output) => {
            result.stonx_version = Some(output.stdout.trim().to_string());
            result.stonx_reachable = true;
        }
        Err(err) => {
            result.probe_error = Some(format!("stonx --version failed: {err}"));
            return Ok(result);
        }
    }

    // 2. 检查 DB 连通性: probe all (无 --tenant 参数,扫描所有 active scope)
    match executor::execute(stonx_bin.clone(), env, path, &AllowedCommand::ProbeAll).await {
        Ok(output) => {
            // 解析 JSON 输出
            if let Ok(parsed) =
                serde_json::from_str::<serde_json::Value>(&output.stdout)
            {
                result.database_reachable = Some(
                    parsed
                        .get("result")
                        .and_then(|v| v.as_str())
                        .map(|v| v == "ok")
                        .unwrap_or(false),
                );
            } else {
                result.probe_error = Some("probe output parse failed".to_string());
            }
        }
        Err(err) => {
            result.probe_error = Some(format!("probe all failed: {err}"));
        }
    }

    Ok(result)
}
