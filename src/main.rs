//! stonex-ops:独立运维诊断工具。
//!
//! ## 两层边界
//!
//! ```text
//! MCP client / agent
//!   -> stonex-ops mcp (stdio JSON-RPC)
//!   -> allowlisted stonx ctl ... --output json
//!   -> stonx runtime / DB / provider probes
//! ```
//!
//! 关键原则:
//! - 不直连数据库,不依赖 stonex 源码
//! - 只调用 `stonx ctl ... --output json` 契约
//! - 命令白名单 + 参数校验 + 审计日志 + 输出脱敏
//! - 第一阶段只做只读诊断

mod audit;
mod executor;
mod mcp_server;
mod redaction;
mod tools;
mod whitelist;

use anyhow::Result;
use clap::{Parser, Subcommand, ValueEnum};
use std::path::PathBuf;

/// StoneX 运维工具
#[derive(Debug, Parser)]
#[command(name = "stonex-ops", version, about = "StoneX ops diagnostic tools")]
struct Cli {
    #[command(subcommand)]
    command: TopCommand,
}

#[derive(Debug, Subcommand)]
enum TopCommand {
    /// 启动 MCP server (stdio JSON-RPC)
    Mcp(McpArgs),
}

#[derive(Debug, clap::Args)]
struct McpArgs {
    /// stonx 二进制路径
    #[arg(
        long,
        default_value = "stonx",
        env = "STONEX_BIN",
        help = "Path to the stonx binary"
    )]
    stonx_bin: PathBuf,

    /// stonx 配置根目录
    #[arg(
        long,
        default_value = "~/.stonex",
        env = "STONEX_PATH",
        help = "StoneX configuration root"
    )]
    path: PathBuf,

    /// 目标环境
    #[arg(
        long,
        env = "STONEX_ENV",
        value_enum,
        default_value = "test",
        help = "StoneX environment"
    )]
    env: OpsEnv,

    /// 审计日志文件路径
    #[arg(long, env = "STONEX_OPS_AUDIT_FILE", help = "Audit log file path")]
    audit_file: Option<PathBuf>,
}

#[derive(Debug, Clone, Copy, ValueEnum, PartialEq, Eq)]
enum OpsEnv {
    #[value(name = "main")]
    Main,
    #[value(name = "test")]
    Test,
    #[value(name = "scratch")]
    Scratch,
}

impl OpsEnv {
    fn as_str(self) -> &'static str {
        match self {
            Self::Main => "main",
            Self::Test => "test",
            Self::Scratch => "scratch",
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        TopCommand::Mcp(args) => {
            let path = expand_tilde(&args.path.to_string_lossy());
            eprintln!(
                "stonex-ops mcp starting: stonx_bin={} env={} path={path}",
                args.stonx_bin.display(),
                args.env.as_str()
            );
            mcp_server::run(
                args.stonx_bin,
                args.env.as_str(),
                &path,
                args.audit_file.as_deref(),
            )
            .await
        }
    }
}

fn expand_tilde(raw: &str) -> String {
    if raw == "~" {
        std::env::var("HOME").unwrap_or_else(|_| ".".to_string())
    } else if let Some(rest) = raw.strip_prefix("~/") {
        let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        format!("{home}/{rest}")
    } else {
        raw.to_string()
    }
}
