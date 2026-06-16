//! 输出脱敏:二次过滤 JSON 输出中的敏感字段。
//!
//! 扫描 JSON object 的所有 key,对匹配敏感模式的 value 替换为 "[redacted]"。

use serde_json::Value;

/// 需要脱敏的字段名模式(小写匹配)。
const SENSITIVE_KEY_PATTERNS: &[&str] = &[
    "token",
    "secret",
    "password",
    "cookie",
    "authorization",
    "api_key",
    "access_token",
    "refresh_token",
    "session",
    "credential",
];

/// 递归脱敏 JSON value 中的敏感字段。
pub(crate) fn redact(value: &mut Value) {
    match value {
        Value::Object(map) => {
            let keys: Vec<String> = map.keys().cloned().collect();
            for key in keys {
                let key_lower = key.to_lowercase();
                if SENSITIVE_KEY_PATTERNS
                    .iter()
                    .any(|pattern| key_lower.contains(pattern))
                {
                    map.insert(key, Value::String("[redacted]".to_string()));
                } else if let Some(child) = map.get_mut(&key) {
                    redact(child);
                }
            }
        }
        Value::Array(items) => {
            for item in items {
                redact(item);
            }
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn redacts_token_fields() {
        let mut value = json!({
            "status": "ok",
            "access_token": "secret-abc-123",
            "data": {
                "name": "test",
                "api_key": "sk-12345"
            }
        });
        redact(&mut value);
        assert_eq!(value["access_token"], "[redacted]");
        assert_eq!(value["data"]["api_key"], "[redacted]");
        assert_eq!(value["data"]["name"], "test");
    }

    #[test]
    fn redacts_nested_sensitive_fields() {
        let mut value = json!({
            "connections": [
                {"name": "xhs", "token": "abc"},
                {"name": "jst", "session": "xyz"}
            ]
        });
        redact(&mut value);
        assert_eq!(value["connections"][0]["token"], "[redacted]");
        assert_eq!(value["connections"][1]["session"], "[redacted]");
    }

    #[test]
    fn preserves_non_sensitive_fields() {
        let mut value = json!({
            "tenant": "test-123",
            "status": "active",
            "updated_at": "2026-06-16"
        });
        let original = value.clone();
        redact(&mut value);
        assert_eq!(value, original);
    }
}
