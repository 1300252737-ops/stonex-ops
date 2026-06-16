//! worker_jobs:查看 worker 作业列表和状态。
//!
//! 支持按 tenant、status、limit 过滤。

use serde::Serialize;
use std::path::PathBuf;

use crate::executor;
use crate::whitelist::AllowedCommand;

#[derive(Debug, Serialize)]
pub(crate) struct WorkerJobsResult {
    pub jobs: Vec<serde_json::Value>,
    pub filters: WorkerJobsFilters,
}

#[derive(Debug, Serialize)]
pub(crate) struct WorkerJobsFilters {
    pub tenant: Option<String>,
    pub status: Option<String>,
    pub limit: Option<i64>,
}

pub(crate) async fn run(
    stonx_bin: PathBuf,
    env: &str,
    path: &str,
    tenant: Option<&str>,
    status: Option<&str>,
    limit: Option<i64>,
) -> Result<WorkerJobsResult, String> {
    // 校验 status 值
    if let Some(s) = status {
        if !matches!(s, "queued" | "running" | "succeeded" | "failed" | "cancelled") {
            return Err(format!(
                "invalid job status: {s}, valid: queued, running, succeeded, failed, cancelled"
            ));
        }
    }

    let cmd = AllowedCommand::WorkerJobList {
        tenant: tenant.map(|t| t.to_string()),
        status: status.map(|s| s.to_string()),
        limit,
    };

    let output = executor::execute(stonx_bin, env, path, &cmd)
        .await
        .map_err(|e| format!("worker job list failed: {e}"))?;

    let jobs: Vec<serde_json::Value> = serde_json::from_str(&output.stdout)
        .map_err(|e| format!("parse worker job list json: {e}"))?;

    Ok(WorkerJobsResult {
        jobs,
        filters: WorkerJobsFilters {
            tenant: tenant.map(|s| s.to_string()),
            status: status.map(|s| s.to_string()),
            limit,
        },
    })
}
