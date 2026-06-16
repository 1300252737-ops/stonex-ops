//! worker_schedules:查看 worker 调度配置和状态。

use serde::Serialize;
use std::path::PathBuf;

use crate::executor;
use crate::whitelist::AllowedCommand;

#[derive(Debug, Serialize)]
pub(crate) struct WorkerSchedulesResult {
    pub schedules: Vec<serde_json::Value>,
    pub tenant: Option<String>,
}

pub(crate) async fn run(
    stonx_bin: PathBuf,
    env: &str,
    path: &str,
    tenant: Option<&str>,
) -> Result<WorkerSchedulesResult, String> {
    let cmd = AllowedCommand::WorkerScheduleList {
        tenant: tenant.map(|t| t.to_string()),
    };

    let output = executor::execute(stonx_bin, env, path, &cmd)
        .await
        .map_err(|e| format!("worker schedule list failed: {e}"))?;

    let schedules: Vec<serde_json::Value> = serde_json::from_str(&output.stdout)
        .map_err(|e| format!("parse worker schedule list json: {e}"))?;

    Ok(WorkerSchedulesResult {
        schedules,
        tenant: tenant.map(|s| s.to_string()),
    })
}
