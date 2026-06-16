//! ops_report_status:查看最近报表生成状态。
//!
//! 通过 worker job list 查看最近成功的 daily/weekly report 作业。

use serde::Serialize;
use std::path::PathBuf;

use crate::executor;
use crate::whitelist::AllowedCommand;

#[derive(Debug, Serialize)]
pub(crate) struct ReportStatusResult {
    pub tenant: Option<String>,
    pub latest_daily: Option<JobSummary>,
    pub latest_weekly: Option<JobSummary>,
    pub recent_jobs: Vec<JobSummary>,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct JobSummary {
    pub job_id: String,
    pub tenant: String,
    pub shop: String,
    pub kind: String,
    pub status: String,
    pub attempts: String,
    pub run_after: String,
}

pub(crate) async fn run(
    stonx_bin: PathBuf,
    env: &str,
    path: &str,
    tenant: Option<&str>,
) -> Result<ReportStatusResult, String> {
    // 获取最近的 worker job (包括 succeeded 和 failed)
    let cmd = AllowedCommand::WorkerJobList {
        tenant: tenant.map(|t| t.to_string()),
        status: None, // 获取所有状态
        limit: Some(50),
    };

    let output = executor::execute(stonx_bin, env, path, &cmd)
        .await
        .map_err(|e| format!("worker job list for report status failed: {e}"))?;

    let jobs: Vec<serde_json::Value> = serde_json::from_str(&output.stdout)
        .map_err(|e| format!("parse worker job list json: {e}"))?;

    let summaries: Vec<JobSummary> = jobs
        .iter()
        .map(|j| JobSummary {
            job_id: j
                .get("job_id")
                .and_then(|v| v.as_str())
                .unwrap_or("-")
                .to_string(),
            tenant: j
                .get("tenant")
                .and_then(|v| v.as_str())
                .unwrap_or("-")
                .to_string(),
            shop: j
                .get("shop_id")
                .and_then(|v| v.as_str())
                .unwrap_or("-")
                .to_string(),
            kind: j
                .get("kind")
                .and_then(|v| v.as_str())
                .unwrap_or("-")
                .to_string(),
            status: j
                .get("status")
                .and_then(|v| v.as_str())
                .unwrap_or("-")
                .to_string(),
            attempts: j
                .get("attempts")
                .and_then(|v| v.as_str())
                .unwrap_or("-")
                .to_string(),
            run_after: j
                .get("run_after")
                .and_then(|v| v.as_str())
                .unwrap_or("-")
                .to_string(),
        })
        .collect();

    let latest_daily = summaries
        .iter()
        .filter(|s| s.kind == "daily" && s.status == "succeeded")
        .next()
        .cloned();

    let latest_weekly = summaries
        .iter()
        .filter(|s| s.kind == "weekly" && s.status == "succeeded")
        .next()
        .cloned();

    Ok(ReportStatusResult {
        tenant: tenant.map(|t| t.to_string()),
        latest_daily,
        latest_weekly,
        recent_jobs: summaries,
    })
}
