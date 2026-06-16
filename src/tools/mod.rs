//! MCP 工具实现。
//!
//! 每个工具:
//! 1. 校验输入参数
//! 2. 构造白名单命令
//! 3. 通过 executor 执行
//! 4. 脱敏输出
//! 5. 返回结构化 JSON

pub(crate) mod data_freshness;
pub(crate) mod env_check;
pub(crate) mod probe_connections;
pub(crate) mod report_status;
pub(crate) mod tenant_list;
pub(crate) mod tenant_show;
pub(crate) mod worker_jobs;
pub(crate) mod worker_schedules;
