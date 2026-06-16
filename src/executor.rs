//! 沙箱执行器:通过 `std::process::Command` 安全调用 `stonx ctl --output json`。
//!
//! 关键安全措施:
//! - 不通过 shell 执行,使用 `Command::new` + 分离的参数列表
//! - 分级超时,防止 hang
//! - 限制输出大小,防止 OOM
//! - 不暴露 stderr 中的内部信息给外部

use std::path::PathBuf;
use std::process::Stdio;
use std::time::Duration;

use anyhow::{Context, bail};

use crate::whitelist::AllowedCommand;

/// 最大输出字节(1MB,防止 OOM)。
const MAX_OUTPUT_BYTES: usize = 1_048_576;

/// 操作类型对应的超时。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum OpKind {
    /// 读操作:tenant list/show, worker list (快速)
    Read,
    /// 探测操作:probe (需要调外部 API,较慢)
    Probe,
}

impl OpKind {
    fn timeout(self) -> Duration {
        match self {
            OpKind::Read => Duration::from_secs(15),
            OpKind::Probe => Duration::from_secs(45),
        }
    }
}

impl AllowedCommand {
    /// 返回此命令对应的操作类型(决定超时)。
    pub(crate) fn op_kind(&self) -> OpKind {
        match self {
            Self::TenantList
            | Self::TenantShow { .. }
            | Self::WorkerScheduleList { .. }
            | Self::WorkerJobList { .. }
            | Self::StonxVersion => OpKind::Read,
            Self::Probe { .. } | Self::ProbeAll => OpKind::Probe,
        }
    }
}

#[derive(Debug, Clone)]
pub(crate) struct ExecutionResult {
    pub stdout: String,
    pub exit_code: Option<i32>,
    pub duration_ms: i64,
}

/// 执行一个白名单化命令。
pub(crate) async fn execute(
    stonx_bin: PathBuf,
    env: &str,
    path: &str,
    command: &AllowedCommand,
) -> anyhow::Result<ExecutionResult> {
    let args = command.to_args(&stonx_bin, env, path);
    let timeout = command.op_kind().timeout();
    let started = std::time::Instant::now();

    let output = tokio::time::timeout(timeout, async {
        tokio::process::Command::new(&args[0])
            .args(&args[1..])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .output()
            .await
    })
    .await
    .map_err(|_| {
        anyhow::anyhow!(
            "stonx command timed out after {}s: {}",
            timeout.as_secs(),
            args.join(" ")
        )
    })?
    .with_context(|| format!("execute stonx failed: args={args:?}"))?;

    let duration_ms = started.elapsed().as_millis() as i64;
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();

    if stdout.len() > MAX_OUTPUT_BYTES {
        bail!(
            "stonx output too large: {} bytes (max {MAX_OUTPUT_BYTES})",
            stdout.len()
        );
    }

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stderr_summary = stderr.lines().take(3).collect::<Vec<_>>().join("; ");
        bail!(
            "stonx exited with {}: {}",
            output
                .status
                .code()
                .map(|c| c.to_string())
                .unwrap_or_else(|| "signal".to_string()),
            stderr_summary
        );
    }

    Ok(ExecutionResult {
        stdout,
        exit_code: output.status.code(),
        duration_ms,
    })
}
