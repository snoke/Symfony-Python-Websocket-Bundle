#[derive(Clone)]
pub(crate) struct Config {
    pub(crate) jwt_alg: String,
    pub(crate) jwt_user_id_claim: String,
    pub(crate) jwt_public_key: String,
    pub(crate) jwt_public_key_file: String,
    pub(crate) jwt_jwks_url: String,
    pub(crate) jwt_issuer: String,
    pub(crate) jwt_audience: String,
    pub(crate) jwt_leeway: i64,
    pub(crate) gateway_role: String,
    pub(crate) ws_mode: String,
    pub(crate) events_mode: String,
    pub(crate) symfony_webhook_url: String,
    pub(crate) symfony_webhook_secret: String,
    pub(crate) gateway_api_key: String,
    pub(crate) redis_dsn: String,
    pub(crate) redis_stream: String,
    pub(crate) redis_inbox_stream: String,
    pub(crate) redis_events_stream: String,
    pub(crate) presence_redis_dsn: String,
    pub(crate) presence_redis_prefix: String,
    pub(crate) presence_ttl_seconds: i64,
    pub(crate) presence_strategy: String,
    pub(crate) presence_heartbeat_seconds: i64,
    pub(crate) presence_grace_seconds: i64,
    pub(crate) presence_refresh_on_message: bool,
    pub(crate) presence_refresh_min_interval_seconds: i64,
    pub(crate) presence_refresh_queue_size: usize,
    pub(crate) webhook_retry_attempts: u32,
    pub(crate) webhook_retry_base_seconds: f64,
    pub(crate) webhook_timeout_seconds: f64,
    pub(crate) ws_rate_limit_per_sec: f64,
    pub(crate) ws_rate_limit_burst: f64,
    pub(crate) ws_outbox_queue_size: usize,
    pub(crate) ws_outbox_drop_strategy: String,
    pub(crate) outbox_strip_internal: bool,
    pub(crate) redis_publish_batch_max: usize,
    pub(crate) redis_publish_batch_interval_ms: u64,
    pub(crate) redis_publish_batch_queue_size: usize,
    pub(crate) json_buffer_pool_size: usize,
    pub(crate) json_buffer_pool_bytes: usize,
    pub(crate) redis_stream_maxlen: usize,
    pub(crate) replay_strategy: String,
    pub(crate) ordering_strategy: String,
    pub(crate) ordering_topic_field: String,
    pub(crate) ordering_subject_source: String,
    pub(crate) channel_routing_strategy: String,
    pub(crate) ordering_partition_mode: String,
    pub(crate) ordering_partition_max_len: usize,
    pub(crate) snowflake_enabled: bool,
    pub(crate) snowflake_worker_id: u16,
    pub(crate) snowflake_epoch_ms: i64,
    pub(crate) rabbitmq_dsn: String,
    pub(crate) rabbitmq_queue: String,
    pub(crate) rabbitmq_exchange: String,
    pub(crate) rabbitmq_routing_key: String,
    pub(crate) rabbitmq_queue_ttl_ms: i64,
    pub(crate) rabbitmq_inbox_exchange: String,
    pub(crate) rabbitmq_inbox_routing_key: String,
    pub(crate) rabbitmq_inbox_queue: String,
    pub(crate) rabbitmq_inbox_queue_ttl_ms: i64,
    pub(crate) rabbitmq_events_exchange: String,
    pub(crate) rabbitmq_events_routing_key: String,
    pub(crate) rabbitmq_events_queue: String,
    pub(crate) rabbitmq_events_queue_ttl_ms: i64,
    pub(crate) rabbitmq_dlq_queue: String,
    pub(crate) rabbitmq_dlq_exchange: String,
    pub(crate) rabbitmq_replay_target_exchange: String,
    pub(crate) rabbitmq_replay_target_routing_key: String,
    pub(crate) rabbitmq_replay_max_batch: i64,
    pub(crate) replay_api_key: String,
    pub(crate) replay_rate_limit_strategy: String,
    pub(crate) replay_rate_limit_per_minute: i64,
    pub(crate) replay_rate_limit_window_seconds: i64,
    pub(crate) replay_rate_limit_redis_dsn: String,
    pub(crate) replay_rate_limit_prefix: String,
    pub(crate) replay_rate_limit_key: String,
    pub(crate) replay_idempotency_strategy: String,
    pub(crate) replay_idempotency_ttl_seconds: i64,
    pub(crate) replay_idempotency_redis_dsn: String,
    pub(crate) replay_idempotency_prefix: String,
    pub(crate) replay_idempotency_header: String,
    pub(crate) replay_idempotency_payload_field: String,
    pub(crate) replay_audit_log: bool,
    pub(crate) tracing_trace_id_field: String,
    pub(crate) tracing_header_name: String,
    pub(crate) log_format: String,
    pub(crate) log_level: String,
}

impl Config {
    pub(crate) fn from_env() -> Self {
        let jwt_alg = env_str("JWT_ALG", "RS256");
        let jwt_user_id_claim = env_str("JWT_USER_ID_CLAIM", "user_id");
        let jwt_public_key_file = env_str("JWT_PUBLIC_KEY_FILE", "");
        let mut jwt_public_key = env_str("JWT_PUBLIC_KEY", "");
        if jwt_public_key.is_empty() && !jwt_public_key_file.is_empty() {
            if let Ok(contents) = std::fs::read_to_string(&jwt_public_key_file) {
                jwt_public_key = contents;
            }
        }
        let jwt_jwks_url = env_str("JWT_JWKS_URL", "");
        let jwt_issuer = env_str("JWT_ISSUER", "");
        let jwt_audience = env_str("JWT_AUDIENCE", "");
        let jwt_leeway = env_i64("JWT_LEEWAY", 0);
        let gateway_role = env_str("GATEWAY_ROLE", "both").to_lowercase();
        let ws_mode = env_str("WS_MODE", "terminator").to_lowercase();
        let mut events_mode = env_str("EVENTS_MODE", "").to_lowercase();
        if events_mode.is_empty() {
            events_mode = if ws_mode == "core" { "broker" } else { "webhook" }.to_string();
        }
        if !matches!(events_mode.as_str(), "broker" | "webhook" | "both" | "none") {
            events_mode = if ws_mode == "core" { "broker" } else { "webhook" }.to_string();
        }
        let symfony_webhook_url = env_str("SYMFONY_WEBHOOK_URL", "");
        let symfony_webhook_secret = env_str("SYMFONY_WEBHOOK_SECRET", "");
        let gateway_api_key = env_str("GATEWAY_API_KEY", "");
        let redis_dsn = env_str("REDIS_DSN", "");
        let redis_stream = env_str("REDIS_STREAM", "ws.outbox");
        let redis_inbox_stream = env_str("REDIS_INBOX_STREAM", "ws.inbox");
        let redis_events_stream = env_str("REDIS_EVENTS_STREAM", "ws.events");
        let presence_redis_dsn = env_str("PRESENCE_REDIS_DSN", &redis_dsn);
        let presence_redis_prefix = env_str("PRESENCE_REDIS_PREFIX", "presence:");
        let presence_ttl_seconds = env_i64("PRESENCE_TTL_SECONDS", 120);
        let presence_strategy = env_str("PRESENCE_STRATEGY", "ttl").to_lowercase();
        let presence_heartbeat_seconds = env_i64("PRESENCE_HEARTBEAT_SECONDS", 30);
        let presence_grace_seconds = env_i64("PRESENCE_GRACE_SECONDS", 15);
        let presence_refresh_on_message = env_bool("PRESENCE_REFRESH_ON_MESSAGE", true);
        let presence_refresh_min_interval_seconds =
            env_i64("PRESENCE_REFRESH_MIN_INTERVAL_SECONDS", 0);
        let presence_refresh_queue_size = env_usize("PRESENCE_REFRESH_QUEUE_SIZE", 1024);
        let webhook_retry_attempts = env_u32("WEBHOOK_RETRY_ATTEMPTS", 3);
        let webhook_retry_base_seconds = env_f64("WEBHOOK_RETRY_BASE_SECONDS", 0.5);
        let webhook_timeout_seconds = env_f64("WEBHOOK_TIMEOUT_SECONDS", 5.0);
        let ws_rate_limit_per_sec = env_f64("WS_RATE_LIMIT_PER_SEC", 10.0);
        let ws_rate_limit_burst = env_f64("WS_RATE_LIMIT_BURST", 20.0);
        let ws_outbox_queue_size = env_usize("WS_OUTBOX_QUEUE_SIZE", 1024);
        let ws_outbox_drop_strategy =
            env_str("WS_OUTBOX_DROP_STRATEGY", "drop_oldest").to_lowercase();
        let outbox_strip_internal = env_bool("OUTBOX_STRIP_INTERNAL", false);
        let redis_publish_batch_max = env_usize("REDIS_PUBLISH_BATCH_MAX", 0);
        let redis_publish_batch_interval_ms = env_u64("REDIS_PUBLISH_BATCH_INTERVAL_MS", 5);
        let redis_publish_batch_queue_size = env_usize("REDIS_PUBLISH_BATCH_QUEUE_SIZE", 1024);
        let json_buffer_pool_size = env_usize("JSON_BUFFER_POOL_SIZE", 64);
        let json_buffer_pool_bytes = env_usize("JSON_BUFFER_POOL_BYTES", 16384);
        let redis_stream_maxlen = env_usize("REDIS_STREAM_MAXLEN", 0);
        let replay_strategy = env_str("REPLAY_STRATEGY", "none").to_lowercase();
        let ordering_strategy = env_str("ORDERING_STRATEGY", "none").to_lowercase();
        let ordering_topic_field = env_str("ORDERING_TOPIC_FIELD", "topic");
        let ordering_subject_source = env_str("ORDERING_SUBJECT_SOURCE", "subject");
        let channel_routing_strategy = env_str("CHANNEL_ROUTING_STRATEGY", "none").to_lowercase();
        let ordering_partition_mode = env_str("ORDERING_PARTITION_MODE", "suffix").to_lowercase();
        let ordering_partition_max_len = env_usize("ORDERING_PARTITION_MAX_LEN", 64);
        let snowflake_enabled = env_bool("SNOWFLAKE_ENABLED", true);
        let snowflake_worker_id = env_i64("SNOWFLAKE_WORKER_ID", 0);
        let snowflake_epoch_ms = env_i64("SNOWFLAKE_EPOCH_MS", 1704067200000);
        let rabbitmq_dsn = env_str("RABBITMQ_DSN", "");
        let rabbitmq_queue = env_str("RABBITMQ_QUEUE", "");
        let rabbitmq_exchange = env_str("RABBITMQ_EXCHANGE", "");
        let rabbitmq_routing_key = env_str("RABBITMQ_ROUTING_KEY", "");
        let rabbitmq_queue_ttl_ms = env_i64("RABBITMQ_QUEUE_TTL_MS", 0);
        let rabbitmq_inbox_exchange = env_str("RABBITMQ_INBOX_EXCHANGE", "");
        let rabbitmq_inbox_routing_key = env_str("RABBITMQ_INBOX_ROUTING_KEY", "");
        let rabbitmq_inbox_queue = env_str("RABBITMQ_INBOX_QUEUE", "");
        let rabbitmq_inbox_queue_ttl_ms = env_i64("RABBITMQ_INBOX_QUEUE_TTL_MS", 0);
        let rabbitmq_events_exchange = env_str("RABBITMQ_EVENTS_EXCHANGE", "");
        let rabbitmq_events_routing_key = env_str("RABBITMQ_EVENTS_ROUTING_KEY", "");
        let rabbitmq_events_queue = env_str("RABBITMQ_EVENTS_QUEUE", "");
        let rabbitmq_events_queue_ttl_ms = env_i64("RABBITMQ_EVENTS_QUEUE_TTL_MS", 0);
        let rabbitmq_dlq_queue = env_str("RABBITMQ_DLQ_QUEUE", "");
        let rabbitmq_dlq_exchange = env_str("RABBITMQ_DLQ_EXCHANGE", "");
        let rabbitmq_replay_target_exchange = env_str("RABBITMQ_REPLAY_TARGET_EXCHANGE", "");
        let rabbitmq_replay_target_routing_key = env_str("RABBITMQ_REPLAY_TARGET_ROUTING_KEY", "");
        let rabbitmq_replay_max_batch = env_i64("RABBITMQ_REPLAY_MAX_BATCH", 100);
        let replay_api_key = env_str("REPLAY_API_KEY", "");
        let replay_rate_limit_strategy = env_str("REPLAY_RATE_LIMIT_STRATEGY", "in_memory").to_lowercase();
        let replay_rate_limit_per_minute = env_i64("REPLAY_RATE_LIMIT_PER_MINUTE", 10);
        let replay_rate_limit_window_seconds = env_i64("REPLAY_RATE_LIMIT_WINDOW_SECONDS", 60);
        let replay_rate_limit_redis_dsn = env_str("REPLAY_RATE_LIMIT_REDIS_DSN", &redis_dsn);
        let replay_rate_limit_prefix = env_str("REPLAY_RATE_LIMIT_PREFIX", "replay:rate:");
        let replay_rate_limit_key = env_str("REPLAY_RATE_LIMIT_KEY", "api_key_or_ip").to_lowercase();
        let replay_idempotency_strategy =
            env_str("REPLAY_IDEMPOTENCY_STRATEGY", "in_memory").to_lowercase();
        let replay_idempotency_ttl_seconds = env_i64("REPLAY_IDEMPOTENCY_TTL_SECONDS", 600);
        let replay_idempotency_redis_dsn =
            env_str("REPLAY_IDEMPOTENCY_REDIS_DSN", &replay_rate_limit_redis_dsn);
        let replay_idempotency_prefix = env_str("REPLAY_IDEMPOTENCY_PREFIX", "replay:id:");
        let replay_idempotency_header = env_str("REPLAY_IDEMPOTENCY_HEADER", "Idempotency-Key");
        let replay_idempotency_payload_field =
            env_str("REPLAY_IDEMPOTENCY_PAYLOAD_FIELD", "idempotency_key");
        let replay_audit_log = env_bool("REPLAY_AUDIT_LOG", true);
        let tracing_trace_id_field = env_str("WS_TRACE_ID_FIELD", "trace_id");
        let tracing_header_name = env_str("WS_TRACE_HEADER_NAME", "X-Trace-Id");
        let log_format = env_str("LOG_FORMAT", "json");
        let log_level = env_str("LOG_LEVEL", "info");

        let replay_rate_limit_strategy = match replay_rate_limit_strategy.as_str() {
            "in_memory" | "redis" | "none" => replay_rate_limit_strategy,
            _ => "in_memory".to_string(),
        };
        let replay_rate_limit_key = match replay_rate_limit_key.as_str() {
            "api_key" | "ip" | "api_key_or_ip" | "api_key_and_ip" => replay_rate_limit_key,
            _ => "api_key_or_ip".to_string(),
        };
        let ordering_partition_mode = match ordering_partition_mode.as_str() {
            "suffix" | "none" => ordering_partition_mode,
            _ => "suffix".to_string(),
        };
        let gateway_role = match gateway_role.as_str() {
            "read" | "write" | "both" => gateway_role,
            _ => "both".to_string(),
        };
        let presence_strategy = match presence_strategy.as_str() {
            "ttl" | "heartbeat" | "session" => presence_strategy,
            _ => "ttl".to_string(),
        };
        let ws_outbox_drop_strategy = match ws_outbox_drop_strategy.as_str() {
            "drop_oldest" | "drop_newest" => ws_outbox_drop_strategy,
            _ => "drop_oldest".to_string(),
        };
        let replay_strategy = match replay_strategy.as_str() {
            "none" | "bounded" | "durable" => replay_strategy,
            _ => "none".to_string(),
        };
        let channel_routing_strategy = match channel_routing_strategy.as_str() {
            "none" | "channel_id" => channel_routing_strategy,
            _ => "none".to_string(),
        };
        let replay_rate_limit_per_minute = replay_rate_limit_per_minute.max(0);
        let replay_rate_limit_window_seconds = if replay_rate_limit_window_seconds <= 0 {
            60
        } else {
            replay_rate_limit_window_seconds
        };
        let ws_outbox_queue_size = ws_outbox_queue_size.clamp(1, 100000);
        let redis_publish_batch_interval_ms = redis_publish_batch_interval_ms.max(1);
        let redis_publish_batch_queue_size = redis_publish_batch_queue_size.clamp(1, 100000);
        let json_buffer_pool_size = json_buffer_pool_size.clamp(1, 10000);
        let json_buffer_pool_bytes = json_buffer_pool_bytes.clamp(256, 1024 * 1024);
        let redis_stream_maxlen = redis_stream_maxlen.min(1_000_000);
        let snowflake_epoch_ms = if snowflake_epoch_ms > 0 {
            snowflake_epoch_ms
        } else {
            1704067200000
        };
        let snowflake_worker_id = snowflake_worker_id.clamp(0, 1023) as u16;
        let outbox_strip_internal = if outbox_strip_internal {
            true
        } else {
            gateway_role == "read"
        };

        Self {
            jwt_alg,
            jwt_user_id_claim,
            jwt_public_key,
            jwt_public_key_file,
            jwt_jwks_url,
            jwt_issuer,
            jwt_audience,
            jwt_leeway,
            gateway_role,
            ws_mode,
            events_mode,
            symfony_webhook_url,
            symfony_webhook_secret,
            gateway_api_key,
            redis_dsn,
            redis_stream,
            redis_inbox_stream,
            redis_events_stream,
            presence_redis_dsn,
            presence_redis_prefix,
            presence_ttl_seconds,
            presence_strategy,
            presence_heartbeat_seconds,
            presence_grace_seconds,
            presence_refresh_on_message,
            presence_refresh_min_interval_seconds,
            presence_refresh_queue_size,
            webhook_retry_attempts,
            webhook_retry_base_seconds,
            webhook_timeout_seconds,
            ws_rate_limit_per_sec,
            ws_rate_limit_burst,
            ws_outbox_queue_size,
            ws_outbox_drop_strategy,
            outbox_strip_internal,
            redis_publish_batch_max,
            redis_publish_batch_interval_ms,
            redis_publish_batch_queue_size,
            json_buffer_pool_size,
            json_buffer_pool_bytes,
            redis_stream_maxlen,
            replay_strategy,
            ordering_strategy,
            ordering_topic_field,
            ordering_subject_source,
            channel_routing_strategy,
            ordering_partition_mode,
            ordering_partition_max_len,
            snowflake_enabled,
            snowflake_worker_id,
            snowflake_epoch_ms,
            rabbitmq_dsn,
            rabbitmq_queue,
            rabbitmq_exchange,
            rabbitmq_routing_key,
            rabbitmq_queue_ttl_ms,
            rabbitmq_inbox_exchange,
            rabbitmq_inbox_routing_key,
            rabbitmq_inbox_queue,
            rabbitmq_inbox_queue_ttl_ms,
            rabbitmq_events_exchange,
            rabbitmq_events_routing_key,
            rabbitmq_events_queue,
            rabbitmq_events_queue_ttl_ms,
            rabbitmq_dlq_queue,
            rabbitmq_dlq_exchange,
            rabbitmq_replay_target_exchange,
            rabbitmq_replay_target_routing_key,
            rabbitmq_replay_max_batch,
            replay_api_key,
            replay_rate_limit_strategy,
            replay_rate_limit_per_minute,
            replay_rate_limit_window_seconds,
            replay_rate_limit_redis_dsn,
            replay_rate_limit_prefix,
            replay_rate_limit_key,
            replay_idempotency_strategy,
            replay_idempotency_ttl_seconds,
            replay_idempotency_redis_dsn,
            replay_idempotency_prefix,
            replay_idempotency_header,
            replay_idempotency_payload_field,
            replay_audit_log,
            tracing_trace_id_field,
            tracing_header_name,
            log_format,
            log_level,
        }
    }

    pub(crate) fn events_mode_broker(&self) -> bool {
        matches!(self.events_mode.as_str(), "broker" | "both")
    }

    pub(crate) fn events_mode_webhook(&self) -> bool {
        matches!(self.events_mode.as_str(), "webhook" | "both")
    }

    pub(crate) fn presence_enabled(&self) -> bool {
        !self.presence_redis_dsn.is_empty()
    }

    pub(crate) fn role_read(&self) -> bool {
        matches!(self.gateway_role.as_str(), "read" | "both")
    }

    pub(crate) fn role_write(&self) -> bool {
        matches!(self.gateway_role.as_str(), "write" | "both")
    }

    pub(crate) fn ws_outbox_drop_oldest(&self) -> bool {
        self.ws_outbox_drop_strategy == "drop_oldest"
    }

    pub(crate) fn channel_routing_enabled(&self) -> bool {
        self.channel_routing_strategy == "channel_id"
    }

    pub(crate) fn tracing_trace_id_field(&self) -> &str {
        &self.tracing_trace_id_field
    }

    pub(crate) fn tracing_header_name(&self) -> &str {
        &self.tracing_header_name
    }
}

fn env_str(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_i64(key: &str, default: i64) -> i64 {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse::<i64>().ok())
        .unwrap_or(default)
}

fn env_u32(key: &str, default: u32) -> u32 {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse::<u32>().ok())
        .unwrap_or(default)
}

fn env_u64(key: &str, default: u64) -> u64 {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse::<u64>().ok())
        .unwrap_or(default)
}

fn env_usize(key: &str, default: usize) -> usize {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or(default)
}

fn env_f64(key: &str, default: f64) -> f64 {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .unwrap_or(default)
}

fn env_bool(key: &str, default: bool) -> bool {
    std::env::var(key)
        .ok()
        .map(|v| matches!(v.to_lowercase().as_str(), "1" | "true" | "yes" | "on"))
        .unwrap_or(default)
}
