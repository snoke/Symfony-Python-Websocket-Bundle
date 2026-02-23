use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub(crate) struct MessageFlags {
    #[serde(default, skip_serializing_if = "is_false")]
    pub(crate) encrypted: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) qos: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(crate) struct InternalMessage {
    #[serde(default = "schema_v1")]
    pub(crate) schema_version: u8,
    pub(crate) internal_id: String,
    pub(crate) timestamp_ms: i64,
    pub(crate) user_id: String,
    pub(crate) channel_id: String,
    #[serde(default)]
    pub(crate) flags: MessageFlags,
    pub(crate) payload: Value,
}

impl InternalMessage {
    pub(crate) fn to_client_payload(&self) -> Value {
        let mut payload = json!({
            "id": self.internal_id,
            "ts": self.timestamp_ms,
            "channel_id": self.channel_id,
            "payload": self.payload,
        });
        if let Some(map) = payload.as_object_mut() {
            if self.flags.encrypted {
                map.insert("encrypted".to_string(), Value::Bool(true));
            }
            if let Some(qos) = &self.flags.qos {
                map.insert("qos".to_string(), Value::String(qos.clone()));
            }
        }
        payload
    }
}

pub(crate) fn message_channel_id(data: &Value, fallback: &str) -> String {
    if let Some(value) = data.get("channel_id") {
        let id = value_to_string(value);
        if !id.is_empty() {
            return id;
        }
    }
    if let Some(value) = data.get("channel") {
        let id = value_to_string(value);
        if !id.is_empty() {
            return id;
        }
    }
    if let Some(value) = data.get("topic") {
        let id = value_to_string(value);
        if !id.is_empty() {
            return id;
        }
    }
    fallback.to_string()
}

pub(crate) fn message_payload(data: &Value) -> Value {
    data.get("payload").cloned().unwrap_or_else(|| data.clone())
}

pub(crate) fn message_flags(data: &Value) -> MessageFlags {
    let mut flags = MessageFlags::default();
    if let Some(value) = data.get("encrypted").and_then(|v| v.as_bool()) {
        flags.encrypted = value;
    }
    if let Some(value) = data
        .get("flags")
        .and_then(|v| v.get("encrypted"))
        .and_then(|v| v.as_bool())
    {
        flags.encrypted = value;
    }
    if let Some(value) = data.get("qos") {
        let qos = value_to_string(value);
        if !qos.is_empty() {
            flags.qos = Some(qos);
        }
    }
    if let Some(value) = data
        .get("flags")
        .and_then(|v| v.get("qos"))
    {
        let qos = value_to_string(value);
        if !qos.is_empty() {
            flags.qos = Some(qos);
        }
    }
    flags
}

fn is_false(value: &bool) -> bool {
    !*value
}

fn schema_v1() -> u8 {
    1
}

fn value_to_string(value: &Value) -> String {
    if let Some(s) = value.as_str() {
        return s.to_string();
    }
    if let Some(n) = value.as_i64() {
        return n.to_string();
    }
    if let Some(n) = value.as_u64() {
        return n.to_string();
    }
    if let Some(n) = value.as_f64() {
        let s = n.to_string();
        if !s.is_empty() {
            return s;
        }
    }
    String::new()
}
