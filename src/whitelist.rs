//! 命令白名单:定义允许的 stonx ctl 命令及其参数限制。
//!
//! 上游 CLI 契约: `stonx ctl <subcommand> --output json [...]`
//! `--output json` 是子命令级 flag,不是全局 flag。

use std::path::PathBuf;

#[derive(Debug, Clone)]
pub(crate) enum AllowedCommand {
    /// `stonx ctl tenant list --output json`
    TenantList,
    /// `stonx ctl tenant show --tenant <id> --output json`
    TenantShow { tenant: String },
    /// `stonx ctl probe [--tenant <id>] [--shop-id <id>] --output json`
    Probe {
        tenant: Option<String>,
        shop_id: Option<String>,
    },
    /// `stonx ctl worker schedule list [--tenant <id>] --output json`
    WorkerScheduleList { tenant: Option<String> },
    /// `stonx ctl worker job list [--tenant <id>] [--status <s>] [--limit <n>] --output json`
    WorkerJobList {
        tenant: Option<String>,
        status: Option<String>,
        limit: Option<i64>,
    },
    /// `stonx --version`
    StonxVersion,
    /// `stonx ctl probe --output json` (所有 active scope)
    ProbeAll,
}

fn is_safe_identity(value: &str) -> bool {
    !value.is_empty()
        && value
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
        && value.len() <= 128
}

impl AllowedCommand {
    /// 构造命令行参数列表。`--output json` 放在子命令之后。
    pub(crate) fn to_args(&self, stonx_bin: &PathBuf, env: &str, path: &str) -> Vec<String> {
        let mut args = vec![
            stonx_bin.to_string_lossy().to_string(),
            format!("--env={env}"),
            format!("--path={path}"),
            "ctl".to_string(),
        ];
        match self {
            Self::TenantList => {
                args.push("tenant".to_string());
                args.push("list".to_string());
                args.push("--output=json".to_string());
            }
            Self::TenantShow { tenant } => {
                assert!(is_safe_identity(tenant), "unsafe tenant identity");
                args.push("tenant".to_string());
                args.push("show".to_string());
                args.push(format!("--tenant={tenant}"));
                args.push("--output=json".to_string());
            }
            Self::Probe { tenant, shop_id } => {
                args.push("probe".to_string());
                if let Some(tenant) = tenant {
                    assert!(is_safe_identity(tenant), "unsafe tenant identity");
                    args.push(format!("--tenant={tenant}"));
                }
                if let Some(shop_id) = shop_id {
                    assert!(is_safe_identity(shop_id), "unsafe shop_id");
                    args.push(format!("--shop-id={shop_id}"));
                }
                args.push("--output=json".to_string());
            }
            Self::WorkerScheduleList { tenant } => {
                args.push("worker".to_string());
                args.push("schedule".to_string());
                args.push("list".to_string());
                if let Some(tenant) = tenant {
                    assert!(is_safe_identity(tenant), "unsafe tenant identity");
                    args.push(format!("--tenant={tenant}"));
                }
                args.push("--output=json".to_string());
            }
            Self::WorkerJobList {
                tenant,
                status,
                limit,
            } => {
                args.push("worker".to_string());
                args.push("job".to_string());
                args.push("list".to_string());
                if let Some(tenant) = tenant {
                    assert!(is_safe_identity(tenant), "unsafe tenant identity");
                    args.push(format!("--tenant={tenant}"));
                }
                if let Some(status) = status {
                    assert!(matches!(
                        status.as_str(),
                        "queued" | "running" | "succeeded" | "failed" | "cancelled"
                    ));
                    args.push(format!("--status={status}"));
                }
                if let Some(limit) = limit {
                    assert!(*limit >= 1 && *limit <= 500, "limit out of range");
                    args.push(format!("--limit={limit}"));
                }
                args.push("--output=json".to_string());
            }
            Self::StonxVersion => {
                args.clear();
                args.push(stonx_bin.to_string_lossy().to_string());
                args.push("--version".to_string());
            }
            Self::ProbeAll => {
                args.push("probe".to_string());
                args.push("--output=json".to_string());
            }
        }
        args
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn output_json_comes_after_subcommand() {
        let bin = PathBuf::from("stonx");

        let cmd = AllowedCommand::TenantList;
        let args = cmd.to_args(&bin, "test", "~/.stonex");
        let pos_ctl = args.iter().position(|a| a == "ctl").unwrap();
        let pos_output = args.iter().position(|a| a == "--output=json").unwrap();
        assert!(pos_output > pos_ctl, "--output=json must come after ctl subcommand");

        let cmd = AllowedCommand::Probe {
            tenant: Some("t1".to_string()),
            shop_id: None,
        };
        let args = cmd.to_args(&bin, "main", "/opt/.stonex");
        let pos_output = args.iter().position(|a| a == "--output=json").unwrap();
        let pos_probe = args.iter().position(|a| a == "probe").unwrap();
        assert!(pos_output > pos_probe, "--output=json must come after probe");
    }

    #[test]
    fn safe_identity_rejects_shell_chars() {
        assert!(!is_safe_identity("; rm -rf /"));
        assert!(!is_safe_identity("$(whoami)"));
        assert!(!is_safe_identity("`cat /etc/passwd`"));
        assert!(is_safe_identity("tenant-abc_123"));
    }

    #[test]
    fn no_shell_chars_in_args() {
        let cmd = AllowedCommand::TenantShow {
            tenant: "test".to_string(),
        };
        let args = cmd.to_args(&PathBuf::from("stonx"), "test", "~/.stonex");
        for arg in &args {
            assert!(!arg.contains(';'));
            assert!(!arg.contains('|'));
            assert!(!arg.contains('$'));
            assert!(!arg.contains('`'));
        }
    }
}
