use axum::{
    extract::{
        ws::{CloseFrame, Message, WebSocket, WebSocketUpgrade},
        ConnectInfo, Path, Query, State,
    },
    http::HeaderMap,
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use futures::{SinkExt, StreamExt};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{borrow::Cow, collections::HashMap, net::SocketAddr, sync::Arc, time::Duration};
use tracing::{info, warn};

use crate::services::auth::verify_jwt;
use crate::services::broker::{rabbit_outbox_consumer, redis_outbox_consumer, RabbitPublisher};
use crate::services::connections::{ConnectionInfo, ConnectionManager};
use crate::services::events::{publish_connection_event, publish_message_event};
use crate::services::logging_service::init_logging;
use crate::services::metrics::Metrics;
use crate::services::ordering::OrderingService;
use crate::services::presence::PresenceService;
use crate::services::rate_limit::RateLimiter;
use crate::services::replay::{
    audit_log, normalize_replay_key, payload_limit, rate_limit_identity, redis_idempotency_get,
    redis_idempotency_set, redis_rate_limit_allow, replay_from_dlq, ReplayState,
};
use crate::services::settings::Config;
use crate::services::snowflake::SnowflakeGenerator;
use crate::services::utils::{unix_timestamp, unix_timestamp_ms, JsonBufferPool, value_to_string};
use crate::services::redis_batch::RedisBatcher;
use crate::services::message::{InternalMessage, message_channel_id, message_flags, message_payload};

const SIMPLE_PING: &str = r#"{"type":"ping"}"#;
const SIMPLE_HEARTBEAT: &str = r#"{"type":"heartbeat"}"#;
const PONG_MESSAGE: &str = r#"{"type":"pong"}"#;
const HEARTBEAT_ACK_MESSAGE: &str = r#"{"type":"heartbeat_ack"}"#;
const RATE_LIMITED_MESSAGE: &str = r#"{"type":"rate_limited"}"#;
const READ_ONLY_MESSAGE: &str = r#"{"type":"read_only"}"#;

pub(crate) struct AppState {
    pub(crate) config: Config,
    pub(crate) metrics: Arc<Metrics>,
    pub(crate) connections: ConnectionManager,
    pub(crate) ordering: OrderingService,
    pub(crate) presence: PresenceService,
    pub(crate) redis: Option<redis::Client>,
    pub(crate) rabbit: Option<Arc<RabbitPublisher>>,
    pub(crate) replay: ReplayState,
    pub(crate) http: reqwest::Client,
    pub(crate) json_pool: Arc<JsonBufferPool>,
    pub(crate) redis_batcher: Option<RedisBatcher>,
    pub(crate) snowflake: Option<Arc<SnowflakeGenerator>>,
}

impl AppState {
    pub(crate) async fn new(config: Config) -> Self {
        let redis = if config.redis_dsn.is_empty() {
            None
        } else {
            match redis::Client::open(config.redis_dsn.as_str()) {
                Ok(client) => Some(client),
                Err(err) => {
                    warn!("redis.init_failed: {err}");
                    None
                }
            }
        };
        let presence = PresenceService::new(&config);
        let rabbit = if config.rabbitmq_dsn.is_empty() {
            None
        } else {
            Some(Arc::new(RabbitPublisher::new(&config)))
        };
        let replay = ReplayState::new(&config);
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs_f64(config.webhook_timeout_seconds))
            .build()
            .expect("http client");
        let metrics = Arc::new(Metrics::new());
        let json_pool = Arc::new(JsonBufferPool::new(
            config.json_buffer_pool_size,
            config.json_buffer_pool_bytes,
        ));
        let snowflake = if config.snowflake_enabled && config.role_write() {
            Some(Arc::new(SnowflakeGenerator::new(
                config.snowflake_worker_id,
                config.snowflake_epoch_ms,
            )))
        } else {
            None
        };
        let redis_batcher = if let Some(client) = &redis {
            if config.redis_publish_batch_max > 1 {
                Some(RedisBatcher::new(
                    client.clone(),
                    Arc::clone(&metrics),
                    config.redis_publish_batch_max,
                    Duration::from_millis(config.redis_publish_batch_interval_ms),
                    config.redis_publish_batch_queue_size,
                ))
            } else {
                None
            }
        } else {
            None
        };
        Self {
            config,
            metrics,
            connections: ConnectionManager::new(),
            ordering: OrderingService::new(),
            presence,
            redis,
            rabbit,
            replay,
            http,
            json_pool,
            redis_batcher,
            snowflake,
        }
    }

    pub(crate) fn start_background_tasks(self: &Arc<Self>) {
        self.presence.start_worker();
        if self.redis.is_some() && self.config.role_read() {
            let state = Arc::clone(self);
            tokio::spawn(async move {
                redis_outbox_consumer(state).await;
            });
        }
        if !self.config.rabbitmq_dsn.is_empty() && self.config.role_read() {
            let state = Arc::clone(self);
            tokio::spawn(async move {
                rabbit_outbox_consumer(state).await;
            });
        }
    }

    fn next_internal_id(&self) -> String {
        if let Some(generator) = &self.snowflake {
            return generator.next_id_string();
        }
        uuid::Uuid::new_v4().to_string()
    }
}

pub(crate) async fn run() {
    let config = Config::from_env();
    init_logging(&config);
    let state = Arc::new(AppState::new(config).await);

    state.start_background_tasks();

    let app = build_router(Arc::clone(&state));
    let addr = SocketAddr::from(([0, 0, 0, 0], 8000));
    info!("gateway.starting addr={addr}");
    let listener = tokio::net::TcpListener::bind(addr).await.expect("bind");
    axum::serve(listener, app.into_make_service_with_connect_info::<SocketAddr>())
        .await
        .expect("serve");
}

fn build_router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/ws", get(ws_handler))
        .route("/internal/publish", post(publish_handler))
        .route("/internal/replay/rabbitmq", post(replay_handler))
        .route("/metrics", get(metrics_handler))
        .route("/health", get(health_handler))
        .route("/ready", get(ready_handler))
        .route("/internal/connections", get(list_connections_handler))
        .route("/internal/users/:user_id/connections", get(user_connections_handler))
        .with_state(state)
}

async fn ws_handler(
    ws: WebSocketUpgrade,
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(params): Query<HashMap<String, String>>,
) -> impl IntoResponse {
    let token = extract_token(&headers, &params);
    let channels = extract_channels(&params);
    let traceparent = headers
        .get("traceparent")
        .and_then(|v| v.to_str().ok())
        .map(|v| v.to_string());
    ws.on_upgrade(move |socket| handle_socket(socket, state, token, traceparent, channels))
}

fn extract_token(headers: &HeaderMap, params: &HashMap<String, String>) -> Option<String> {
    if let Some(value) = headers.get("authorization").and_then(|v| v.to_str().ok()) {
        if let Some(stripped) = value.strip_prefix("Bearer ") {
            if !stripped.is_empty() {
                return Some(stripped.to_string());
            }
        }
    }
    if let Some(token) = params.get("token") {
        if !token.is_empty() {
            return Some(token.to_string());
        }
    }
    if let Some(token) = params.get("access_token") {
        if !token.is_empty() {
            return Some(token.to_string());
        }
    }
    None
}

fn extract_channels(params: &HashMap<String, String>) -> Vec<String> {
    let mut channels = Vec::new();
    if let Some(value) = params.get("channels") {
        for item in value.split(',') {
            let trimmed = item.trim();
            if !trimmed.is_empty() {
                channels.push(trimmed.to_string());
            }
        }
    }
    if let Some(value) = params.get("channel") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            channels.push(trimmed.to_string());
        }
    }
    channels
}

fn is_exact_json(text: &str, expected: &str) -> bool {
    let trimmed = text.trim();
    trimmed.len() == expected.len() && trimmed == expected
}

async fn handle_control_message(
    state: &Arc<AppState>,
    conn_info: &ConnectionInfo,
    connection_id: &str,
    msg_type: &str,
) {
    if state.config.presence_enabled()
        && (state.config.presence_strategy == "ttl" || state.config.presence_strategy == "heartbeat")
        && (msg_type == "heartbeat" || state.config.presence_refresh_on_message)
    {
        state.presence.refresh(conn_info).await;
    }
    let reply = if msg_type == "ping" {
        PONG_MESSAGE
    } else {
        HEARTBEAT_ACK_MESSAGE
    };
    let outcome = state
        .connections
        .send_message(connection_id, Message::Text(reply.to_string()))
        .await;
    if outcome.sent {
        Metrics::inc(&state.metrics.ws_messages_out_total, 1);
    }
    if outcome.dropped {
        Metrics::inc(&state.metrics.backpressure_dropped_total, 1);
    }
}

async fn handle_socket(
    socket: WebSocket,
    state: Arc<AppState>,
    token: Option<String>,
    traceparent: Option<String>,
    channels: Vec<String>,
) {
    let Some(token) = token else {
        close_ws(socket, "missing token").await;
        return;
    };

    let claims = match verify_jwt(&state.config, &token).await {
        Ok(claims) => claims,
        Err(_) => {
            close_ws(socket, "invalid token").await;
            return;
        }
    };

    let user_id = claims
        .get(&state.config.jwt_user_id_claim)
        .map(value_to_string)
        .unwrap_or_default();
    if user_id.is_empty() {
        close_ws(socket, "missing user_id").await;
        return;
    }

    let mut subjects = vec![format!("user:{user_id}")];
    for channel in channels {
        subjects.push(format!("channel:{channel}"));
    }
    let connection_id = uuid::Uuid::new_v4().to_string();
    let connected_at = unix_timestamp();
    let conn_info = ConnectionInfo {
        connection_id: connection_id.clone(),
        user_id: user_id.clone(),
        subjects: subjects.clone(),
        connected_at,
        traceparent: traceparent.clone(),
    };

    let (mut sender, mut receiver) = socket.split();
    let outbox = Arc::new(crate::services::connections::WsOutbox::new(
        state.config.ws_outbox_queue_size,
        state.config.ws_outbox_drop_oldest(),
    ));

    state.connections.add(conn_info.clone(), Arc::clone(&outbox)).await;
    Metrics::inc(&state.metrics.ws_connections_total, 1);
    info!(
        "ws_connected connection_id={} user_id={}",
        conn_info.connection_id,
        conn_info.user_id
    );

    if state.config.presence_enabled() {
        let presence = state.presence.clone();
        let info_clone = conn_info.clone();
        tokio::spawn(async move {
            presence.set(&info_clone).await;
        });
    }

    publish_connection_event(state.as_ref(), "connected", &conn_info).await;

    let send_task = tokio::spawn(async move {
        while let Some(msg) = outbox.pop().await {
            if sender.send(msg).await.is_err() {
                break;
            }
        }
        outbox.close().await;
    });

    let mut rate_limiter =
        RateLimiter::new(state.config.ws_rate_limit_per_sec, state.config.ws_rate_limit_burst);

    while let Some(Ok(msg)) = receiver.next().await {
        match msg {
            Message::Text(text) => {
                if is_exact_json(&text, SIMPLE_PING) {
                    handle_control_message(&state, &conn_info, &connection_id, "ping").await;
                    continue;
                }
                if is_exact_json(&text, SIMPLE_HEARTBEAT) {
                    handle_control_message(&state, &conn_info, &connection_id, "heartbeat").await;
                    continue;
                }
                let data = serde_json::from_str::<Value>(&text)
                    .unwrap_or_else(|_| json!({"type": "raw", "payload": text}));
                let msg_type = data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                if matches!(msg_type, "ping" | "heartbeat") {
                    handle_control_message(&state, &conn_info, &connection_id, msg_type).await;
                    continue;
                }

                if !rate_limiter.allow() {
                    Metrics::inc(&state.metrics.ws_rate_limited_total, 1);
                    let outcome = state
                        .connections
                        .send_message(
                            &connection_id,
                            Message::Text(RATE_LIMITED_MESSAGE.to_string()),
                        )
                        .await;
                    if outcome.sent {
                        Metrics::inc(&state.metrics.ws_messages_out_total, 1);
                    }
                    if outcome.dropped {
                        Metrics::inc(&state.metrics.backpressure_dropped_total, 1);
                    }
                    continue;
                }

                Metrics::inc(&state.metrics.ws_messages_total, 1);
                if !state.config.role_write() {
                    let outcome = state
                        .connections
                        .send_message(
                            &connection_id,
                            Message::Text(READ_ONLY_MESSAGE.to_string()),
                        )
                        .await;
                    if outcome.sent {
                        Metrics::inc(&state.metrics.ws_messages_out_total, 1);
                    }
                    if outcome.dropped {
                        Metrics::inc(&state.metrics.backpressure_dropped_total, 1);
                    }
                    continue;
                }
                if state.config.presence_enabled()
                    && state.config.presence_refresh_on_message
                    && (state.config.presence_strategy == "ttl"
                        || state.config.presence_strategy == "heartbeat")
                {
                    state.presence.refresh(&conn_info).await;
                }
                let internal_id = state.next_internal_id();
                let timestamp_ms = unix_timestamp_ms();
                let fallback_channel = conn_info
                    .subjects
                    .iter()
                    .find_map(|s| s.strip_prefix("channel:"))
                    .unwrap_or(conn_info.user_id.as_str());
                let channel_id = message_channel_id(&data, fallback_channel);
                let flags = message_flags(&data);
                let payload = message_payload(&data);
                let internal = InternalMessage {
                    internal_id,
                    timestamp_ms,
                    user_id: conn_info.user_id.clone(),
                    channel_id,
                    flags,
                    payload,
                    schema_version: 1,
                };
                publish_message_event(state.as_ref(), &conn_info, &data, &text, &internal).await;
            }
            Message::Close(_) => break,
            _ => {}
        }
    }

    let _ = send_task.await;
    Metrics::inc(&state.metrics.ws_disconnects_total, 1);
    info!(
        "ws_disconnected connection_id={} user_id={}",
        conn_info.connection_id,
        conn_info.user_id
    );
    let _ = state.connections.remove(&connection_id).await;
    if state.config.presence_enabled() {
        let presence = state.presence.clone();
        let info_clone = conn_info.clone();
        tokio::spawn(async move {
            presence.remove(&info_clone).await;
        });
    }
    publish_connection_event(state.as_ref(), "disconnected", &conn_info).await;
}

async fn close_ws(mut socket: WebSocket, reason: &str) {
    let frame = CloseFrame {
        code: 4401,
        reason: Cow::from(reason.to_string()),
    };
    let _ = socket.send(Message::Close(Some(frame))).await;
}

#[derive(Deserialize)]
struct PublishRequest {
    api_key: Option<String>,
    subjects: Option<Vec<String>>,
    payload: Option<Value>,
}

async fn publish_handler(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(payload): Json<PublishRequest>,
) -> impl IntoResponse {
    if !state.config.role_read() {
        return (
            axum::http::StatusCode::FORBIDDEN,
            Json(json!({"detail": "read role required"})),
        )
            .into_response();
    }
    let api_key = payload.api_key.clone().unwrap_or_default();
    if !state.config.gateway_api_key.is_empty() && api_key != state.config.gateway_api_key {
        return (axum::http::StatusCode::UNAUTHORIZED, Json(json!({"detail": "invalid api key"})))
            .into_response();
    }
    let subjects = payload.subjects.unwrap_or_default();
    let message = payload.payload.unwrap_or(Value::Null);
    let stats = state.connections.send_to_subjects(&subjects, &message).await;
    if stats.sent > 0 {
        Metrics::inc(&state.metrics.ws_messages_out_total, stats.sent as u64);
    }
    if stats.dropped > 0 {
        Metrics::inc(&state.metrics.backpressure_dropped_total, stats.dropped as u64);
    }
    Metrics::inc(&state.metrics.publish_total, 1);
    let _traceparent = headers.get("traceparent");
    (
        axum::http::StatusCode::OK,
        Json(json!({"sent": stats.sent})),
    )
        .into_response()
}

async fn replay_handler(
    State(state): State<Arc<AppState>>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
    Json(payload): Json<Value>,
) -> impl IntoResponse {
    if !state.config.role_write() {
        return (
            axum::http::StatusCode::FORBIDDEN,
            Json(json!({"detail": "write role required"})),
        )
            .into_response();
    }
    Metrics::inc(&state.metrics.replay_api_requests_total, 1);
    let request_id = headers
        .get("X-Request-Id")
        .and_then(|v| v.to_str().ok())
        .map(|v| v.to_string())
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
    let caller_ip = addr.ip().to_string();
    let api_key = extract_api_key(&headers, &payload);
    let expected_key = if !state.config.replay_api_key.is_empty() {
        state.config.replay_api_key.clone()
    } else {
        state.config.gateway_api_key.clone()
    };
    if !expected_key.is_empty() && api_key != expected_key {
        Metrics::inc(&state.metrics.replay_api_denied_total, 1);
        audit_log(
            &state,
            "replay_api_denied",
            &request_id,
            &caller_ip,
            Some(&api_key),
            None,
        );
        return (
            axum::http::StatusCode::UNAUTHORIZED,
            Json(json!({"detail": "invalid api key"})),
        )
            .into_response();
    }
    if state.config.rabbitmq_dsn.is_empty() {
        Metrics::inc(&state.metrics.replay_api_errors_total, 1);
        audit_log(
            &state,
            "replay_api_error",
            &request_id,
            &caller_ip,
            Some(&api_key),
            Some("rabbitmq not configured"),
        );
        return (
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"detail": "rabbitmq not configured"})),
        )
            .into_response();
    }

    let identity = normalize_replay_key(&rate_limit_identity(&state.config, &api_key, &caller_ip));
    if state.config.replay_rate_limit_strategy != "none"
        && state.config.replay_rate_limit_per_minute > 0
    {
        let allowed = if state.config.replay_rate_limit_strategy == "redis" {
            match redis_rate_limit_allow(&state.replay, &state.config, &identity).await {
                Ok(value) => value,
                Err(err) => {
                    Metrics::inc(&state.metrics.replay_api_errors_total, 1);
                    audit_log(
                        &state,
                        "replay_api_error",
                        &request_id,
                        &caller_ip,
                        Some(&api_key),
                        Some(&format!("rate_limit_error:{err}")),
                    );
                    return (
                        axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                        Json(json!({"detail": "replay failed"})),
                    )
                        .into_response();
                }
            }
        } else {
            state
                .replay
                .rate_limiter
                .allow(
                    &identity,
                    state.config.replay_rate_limit_per_minute,
                    state.config.replay_rate_limit_window_seconds,
                )
                .await
        };
        if !allowed {
            Metrics::inc(&state.metrics.replay_api_rate_limited_total, 1);
            audit_log(
                &state,
                "replay_api_rate_limited",
                &request_id,
                &caller_ip,
                Some(&api_key),
                Some(&identity),
            );
            return (
                axum::http::StatusCode::TOO_MANY_REQUESTS,
                Json(json!({"detail": "rate limit exceeded"})),
            )
                .into_response();
        }
    }

    let idempotency_header = state.config.replay_idempotency_header.clone();
    let idempotency_payload_field = state.config.replay_idempotency_payload_field.clone();
    let idempotency_key = headers
        .get(&idempotency_header)
        .and_then(|v| v.to_str().ok())
        .map(|v| v.to_string())
        .or_else(|| {
            payload
                .get(&idempotency_payload_field)
                .and_then(|v| v.as_str())
                .map(|v| v.to_string())
        })
        .unwrap_or_default();
    let idempotency_key = if idempotency_key.is_empty() {
        String::new()
    } else {
        normalize_replay_key(&idempotency_key)
    };

    if !idempotency_key.is_empty() && state.config.replay_idempotency_strategy != "none" {
        let cached = if state.config.replay_idempotency_strategy == "redis" {
            match redis_idempotency_get(&state.replay, &state.config, &idempotency_key).await {
                Ok(value) => value,
                Err(err) => {
                    Metrics::inc(&state.metrics.replay_api_errors_total, 1);
                    audit_log(
                        &state,
                        "replay_api_error",
                        &request_id,
                        &caller_ip,
                        Some(&api_key),
                        Some(&format!("idempotency_error:{err}")),
                    );
                    return (
                        axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                        Json(json!({"detail": "replay failed"})),
                    )
                        .into_response();
                }
            }
        } else {
            state.replay.idempotency.get(&idempotency_key).await
        };
        if let Some(replayed) = cached {
            Metrics::inc(&state.metrics.replay_api_idempotent_total, 1);
            audit_log(
                &state,
                "replay_api_idempotent",
                &request_id,
                &caller_ip,
                Some(&api_key),
                Some(&replayed.to_string()),
            );
            return (
                axum::http::StatusCode::OK,
                Json(json!({"replayed": replayed, "idempotent": true})),
            )
                .into_response();
        }
    }

    let mut limit = payload_limit(&payload).unwrap_or(state.config.rabbitmq_replay_max_batch);
    if limit <= 0 {
        return (axum::http::StatusCode::OK, Json(json!({"replayed": 0}))).into_response();
    }
    limit = limit.min(state.config.rabbitmq_replay_max_batch);

    let target_exchange = if state.config.rabbitmq_replay_target_exchange.is_empty() {
        state.config.rabbitmq_inbox_exchange.clone()
    } else {
        state.config.rabbitmq_replay_target_exchange.clone()
    };
    let target_routing_key = if state.config.rabbitmq_replay_target_routing_key.is_empty() {
        state.config.rabbitmq_inbox_routing_key.clone()
    } else {
        state.config.rabbitmq_replay_target_routing_key.clone()
    };

    let replayed = match replay_from_dlq(&state.config, &target_exchange, &target_routing_key, limit).await
    {
        Ok(count) => count,
        Err(err) => {
            Metrics::inc(&state.metrics.replay_api_errors_total, 1);
            audit_log(
                &state,
                "replay_api_error",
                &request_id,
                &caller_ip,
                Some(&api_key),
                Some(&err.to_string()),
            );
            return (
                axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"detail": "replay failed"})),
            )
                .into_response();
        }
    };

    if !idempotency_key.is_empty() && state.config.replay_idempotency_strategy != "none" {
        if state.config.replay_idempotency_strategy == "redis" {
            if let Err(err) =
                redis_idempotency_set(&state.replay, &state.config, &idempotency_key, replayed).await
            {
                warn!("replay.idempotency_failed: {err}");
            }
        } else {
            state
                .replay
                .idempotency
                .set(&idempotency_key, replayed, state.config.replay_idempotency_ttl_seconds)
                .await;
        }
    }
    Metrics::inc(&state.metrics.replay_api_success_total, 1);
    audit_log(
        &state,
        "replay_api_success",
        &request_id,
        &caller_ip,
        Some(&api_key),
        Some(&replayed.to_string()),
    );
    (axum::http::StatusCode::OK, Json(json!({"replayed": replayed}))).into_response()
}

fn extract_api_key(headers: &HeaderMap, payload: &Value) -> String {
    payload
        .get("api_key")
        .and_then(|v| v.as_str())
        .map(|v| v.to_string())
        .or_else(|| {
            headers
                .get("X-API-Key")
                .or_else(|| headers.get("X-Api-Key"))
                .and_then(|v| v.to_str().ok())
                .map(|v| v.to_string())
        })
        .unwrap_or_default()
}

async fn metrics_handler(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    (
        [(axum::http::header::CONTENT_TYPE, "text/plain; version=0.0.4")],
        state.metrics.to_prometheus(state.config.ws_mode.as_str()),
    )
}

async fn health_handler() -> impl IntoResponse {
    Json(json!({"ok": true}))
}

async fn ready_handler() -> impl IntoResponse {
    Json(json!({"ok": true}))
}

#[derive(Deserialize)]
struct ConnectionQuery {
    subject: Option<String>,
    user_id: Option<String>,
}

async fn list_connections_handler(
    State(state): State<Arc<AppState>>,
    Query(query): Query<ConnectionQuery>,
) -> impl IntoResponse {
    let results = state
        .connections
        .list_connections(query.subject, query.user_id)
        .await;
    Json(json!({"connections": results}))
}

async fn user_connections_handler(
    State(state): State<Arc<AppState>>,
    Path(user_id): Path<String>,
) -> impl IntoResponse {
    let results = state
        .connections
        .list_connections(None, Some(user_id))
        .await;
    Json(json!({"connections": results}))
}
