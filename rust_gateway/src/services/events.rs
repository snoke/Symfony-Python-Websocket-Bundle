use hmac::{Hmac, Mac};
use serde_json::{json, Value};
use sha2::Sha256;
use std::time::Duration;
use tracing::warn;

use crate::services::app::AppState;
use crate::services::connections::ConnectionInfo;
use crate::services::metrics::Metrics;
use crate::services::settings::Config;
use crate::services::utils::{normalize_json, value_to_string};

pub(crate) async fn publish_message_event(
    state: &AppState,
    conn: &ConnectionInfo,
    data: &Value,
    raw: &str,
) {
    let traceparent = extract_traceparent(data).or_else(|| conn.traceparent.clone());
    let trace_id = extract_trace_id(data, &state.config);
    let ordering_key = state.ordering.derive_ordering_key(&state.config, conn, data);
    let mut payload = json!({
        "type": "message_received",
        "connection_id": conn.connection_id.clone(),
        "user_id": conn.user_id.clone(),
        "subjects": conn.subjects.clone(),
        "connected_at": conn.connected_at,
        "message": data.clone(),
        "raw": raw,
    });
    if let Some(tp) = traceparent {
        if let Some(map) = payload.as_object_mut() {
            map.insert("traceparent".to_string(), Value::String(tp));
        }
    }
    if let Some(tid) = trace_id {
        if let Some(map) = payload.as_object_mut() {
            map.insert(state.config.tracing_trace_id_field().to_string(), Value::String(tid));
        }
    }
    if !ordering_key.is_empty() {
        if let Some(map) = payload.as_object_mut() {
            map.insert("ordering_key".to_string(), Value::String(ordering_key.clone()));
            map.insert(
                "ordering_strategy".to_string(),
                Value::String(state.config.ordering_strategy.clone()),
            );
        }
    }

    publish_event(
        state,
        "message_received",
        &state.config.redis_inbox_stream,
        &state.config.rabbitmq_inbox_exchange,
        &state.config.rabbitmq_inbox_routing_key,
        &payload,
        &ordering_key,
    )
    .await;
}

pub(crate) async fn publish_connection_event(
    state: &AppState,
    event_type: &str,
    conn: &ConnectionInfo,
) {
    let mut payload = json!({
        "type": event_type,
        "connection_id": conn.connection_id.clone(),
        "user_id": conn.user_id.clone(),
        "subjects": conn.subjects.clone(),
        "connected_at": conn.connected_at,
    });
    if let Some(tp) = &conn.traceparent {
        if let Some(map) = payload.as_object_mut() {
            map.insert("traceparent".to_string(), Value::String(tp.clone()));
        }
    }
    publish_event(
        state,
        event_type,
        &state.config.redis_events_stream,
        &state.config.rabbitmq_events_exchange,
        &state.config.rabbitmq_events_routing_key,
        &payload,
        "",
    )
    .await;
}

async fn publish_event(
    state: &AppState,
    event_type: &str,
    stream: &str,
    exchange: &str,
    routing_key: &str,
    payload: &Value,
    ordering_key: &str,
) {
    let (stream, routing_key) = state
        .ordering
        .apply_partition(&state.config, stream, routing_key, ordering_key);

    let mut encoded_cache: Option<Vec<u8>> = None;
    let mut pooled = false;
    let mut ensure_encoded = |cache: &mut Option<Vec<u8>>| {
        if cache.is_none() {
            let body = normalize_json(payload.clone());
            let mut buffer = state.json_pool.take();
            buffer.clear();
            if serde_json::to_writer(&mut buffer, &body).is_err() {
                buffer.clear();
                buffer.extend_from_slice(b"{}");
            }
            pooled = true;
            *cache = Some(buffer);
        }
    };

    if state.config.events_mode_broker() {
        if let Some(client) = &state.redis {
            if !stream.is_empty() {
                ensure_encoded(&mut encoded_cache);
                let encoded = encoded_cache.as_ref().map(|buf| buf.as_slice()).unwrap_or(b"{}");
                let mut enqueued = false;
                if let Some(batcher) = &state.redis_batcher {
                    if let Some(bytes) = encoded_cache.as_ref() {
                        enqueued = batcher.enqueue(stream.clone(), bytes.clone());
                    }
                }
                if !enqueued {
                    if let Ok(mut conn) = client.get_multiplexed_async_connection().await {
                        let result: redis::RedisResult<()> = redis::cmd("XADD")
                            .arg(&stream)
                            .arg("*")
                            .arg("data")
                            .arg(encoded)
                            .query_async(&mut conn)
                            .await;
                        if result.is_ok() {
                            Metrics::inc(&state.metrics.broker_publish_total, 1);
                        }
                    }
                }
            }
        }
        if let Some(rabbit) = &state.rabbit {
            ensure_encoded(&mut encoded_cache);
            let encoded = encoded_cache.as_ref().map(|buf| buf.as_slice()).unwrap_or(b"{}");
            if rabbit.publish_raw(exchange, routing_key.as_str(), encoded).await {
                Metrics::inc(&state.metrics.broker_publish_total, 1);
            }
        }
    }

    if state.config.events_mode_webhook() {
        if !state.config.symfony_webhook_url.is_empty() {
            ensure_encoded(&mut encoded_cache);
            let body = encoded_cache.clone().unwrap_or_else(|| b"{}".to_vec());
            let mut headers = reqwest::header::HeaderMap::new();
            if let Some(traceparent) = payload.get("traceparent").and_then(|v| v.as_str()) {
                if let Ok(value) = reqwest::header::HeaderValue::from_str(traceparent) {
                    headers.insert("traceparent", value);
                }
            }
            if let Some(trace_id) = payload
                .get(state.config.tracing_trace_id_field())
                .and_then(|v| v.as_str())
            {
                if let Ok(value) = reqwest::header::HeaderValue::from_str(trace_id) {
                    if let Ok(name) = reqwest::header::HeaderName::from_bytes(
                        state.config.tracing_header_name().as_bytes(),
                    ) {
                        headers.insert(name, value);
                    }
                }
            }
            if !state.config.symfony_webhook_secret.is_empty() {
                let signature = hmac_sha256(&state.config.symfony_webhook_secret, &body);
                let value = format!("sha256={signature}");
                if let Ok(header_value) = reqwest::header::HeaderValue::from_str(&value) {
                    headers.insert("X-Webhook-Signature", header_value);
                }
            }
            for attempt in 0..state.config.webhook_retry_attempts.max(1) {
                let response = state
                    .http
                    .post(&state.config.symfony_webhook_url)
                    .headers(headers.clone())
                    .body(body.clone())
                    .send()
                    .await;
                match response {
                    Ok(_) => {
                        Metrics::inc(&state.metrics.webhook_publish_total, 1);
                        return;
                    }
                    Err(err) => {
                        if attempt + 1 >= state.config.webhook_retry_attempts.max(1) {
                            Metrics::inc(&state.metrics.webhook_publish_failed_total, 1);
                            warn!("webhook_failed event_type={} error={}", event_type, err);
                            break;
                        }
                        let backoff =
                            state.config.webhook_retry_base_seconds * 2_f64.powi(attempt as i32);
                        tokio::time::sleep(Duration::from_secs_f64(backoff)).await;
                    }
                }
            }
        }
    }
    if pooled {
        if let Some(buffer) = encoded_cache.take() {
            state.json_pool.put(buffer);
        }
    }
}

fn hmac_sha256(secret: &str, body: &[u8]) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(secret.as_bytes()).expect("hmac key");
    mac.update(body);
    let result = mac.finalize();
    let bytes = result.into_bytes();
    hex::encode(bytes)
}

fn extract_traceparent(data: &Value) -> Option<String> {
    if let Some(value) = data.get("traceparent") {
        let val = value_to_string(value);
        if !val.is_empty() {
            return Some(val);
        }
    }
    if let Some(meta) = data.get("meta") {
        if let Some(value) = meta.get("traceparent") {
            let val = value_to_string(value);
            if !val.is_empty() {
                return Some(val);
            }
        }
    }
    None
}

fn extract_trace_id(data: &Value, config: &Config) -> Option<String> {
    if let Some(value) = data.get(config.tracing_trace_id_field()) {
        let val = value_to_string(value);
        if !val.is_empty() {
            return Some(val);
        }
    }
    if let Some(meta) = data.get("meta") {
        if let Some(value) = meta.get(config.tracing_trace_id_field()) {
            let val = value_to_string(value);
            if !val.is_empty() {
                return Some(val);
            }
        }
    }
    None
}
