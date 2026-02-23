use serde_json::{Map, Value};
use std::collections::BTreeMap;
use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub(crate) fn value_to_string(value: &Value) -> String {
    if let Some(s) = value.as_str() {
        s.to_string()
    } else if let Some(n) = value.as_i64() {
        n.to_string()
    } else if let Some(n) = value.as_u64() {
        n.to_string()
    } else if let Some(f) = value.as_f64() {
        f.to_string()
    } else {
        String::new()
    }
}

pub(crate) fn normalize_json(value: Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut btree = BTreeMap::new();
            for (k, v) in map {
                btree.insert(k, normalize_json(v));
            }
            let mut ordered = Map::new();
            for (k, v) in btree {
                ordered.insert(k, v);
            }
            Value::Object(ordered)
        }
        Value::Array(items) => Value::Array(items.into_iter().map(normalize_json).collect()),
        other => other,
    }
}

pub(crate) fn unix_timestamp() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|_| Duration::from_secs(0))
        .as_secs() as i64
}

pub(crate) fn unix_timestamp_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|_| Duration::from_secs(0))
        .as_millis() as i64
}

pub(crate) fn unix_timestamp_f64() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|_| Duration::from_secs(0))
        .as_secs_f64()
}

pub(crate) struct JsonBufferPool {
    inner: Mutex<Vec<Vec<u8>>>,
    max: usize,
    default_capacity: usize,
}

impl JsonBufferPool {
    pub(crate) fn new(max: usize, default_capacity: usize) -> Self {
        let max = max.max(1);
        let default_capacity = default_capacity.max(256);
        Self {
            inner: Mutex::new(Vec::with_capacity(max.min(256))),
            max,
            default_capacity,
        }
    }

    pub(crate) fn take(&self) -> Vec<u8> {
        let mut guard = self.inner.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        guard.pop().unwrap_or_else(|| Vec::with_capacity(self.default_capacity))
    }

    pub(crate) fn put(&self, mut buffer: Vec<u8>) {
        buffer.clear();
        if buffer.capacity() > self.default_capacity * 4 {
            buffer.shrink_to(self.default_capacity);
        }
        let mut guard = self.inner.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        if guard.len() < self.max {
            guard.push(buffer);
        }
    }
}
