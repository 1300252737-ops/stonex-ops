//! 审计日志:记录每次 MCP tool 调用的 who / when / what / result。
//!
//! 日志格式: JSONL (每行一条),写入 stderr 或指定文件。

use serde::Serialize;
use std::path::Path;
use std::sync::Mutex;

#[derive(Debug, Clone, Serialize)]
pub(crate) struct AuditEntry {
    pub timestamp: String,
    pub tool: String,
    pub arguments: serde_json::Value,
    pub result_status: AuditStatus,
    pub error: Option<String>,
    pub duration_ms: i64,
    pub session_id: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "lowercase")]
pub(crate) enum AuditStatus {
    Success,
    WhitelistDenied,
    ExecutionFailed,
}

pub(crate) struct AuditLogger {
    file: Mutex<Option<std::fs::File>>,
    session_id: String,
}

impl AuditLogger {
    pub fn new(audit_file: Option<&Path>) -> anyhow::Result<Self> {
        let session_id = uuid::Uuid::new_v4().to_string();
        let file = audit_file
            .map(|path| {
                std::fs::OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(path)
            })
            .transpose()?;
        Ok(Self {
            file: Mutex::new(file),
            session_id,
        })
    }

    pub fn session_id(&self) -> &str {
        &self.session_id
    }

    pub fn log(&self, entry: AuditEntry) {
        let line = serde_json::to_string(&entry).unwrap_or_else(|_| {
            r#"{"error":"audit serialization failed"}"#.to_string()
        });
        if let Ok(mut guard) = self.file.lock() {
            if let Some(ref mut file) = *guard {
                use std::io::Write;
                let _ = writeln!(file, "{line}");
            }
        }
        // 始终写 stderr 在开发阶段可见
        eprintln!("[audit] {line}");
    }
}
