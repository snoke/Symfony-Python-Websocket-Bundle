use futures::StreamExt;
use lapin::{
    options::{
        BasicAckOptions, BasicConsumeOptions, BasicPublishOptions, ExchangeDeclareOptions,
        QueueBindOptions, QueueDeclareOptions,
    },
    types::{AMQPValue, FieldTable, LongString},
    BasicProperties, Channel, Connection, ConnectionProperties, ExchangeKind,
};
use serde::Deserialize;
use serde_json::value::RawValue;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;
use tracing::warn;

use crate::services::app::AppState;
use crate::services::metrics::Metrics;
use crate::services::message::InternalMessage;
use crate::services::settings::Config;
use crate::services::utils::normalize_json;

#[derive(Clone)]
struct RabbitConfig {
    dsn: String,
    inbox_exchange: String,
    inbox_routing_key: String,
    inbox_queue: String,
    inbox_queue_ttl_ms: i64,
    events_exchange: String,
    events_routing_key: String,
    events_queue: String,
    events_queue_ttl_ms: i64,
    dlq_exchange: String,
    dlq_queue: String,
}

struct RabbitPublishState {
    connection: Option<Connection>,
    channel: Option<Channel>,
}

#[derive(Deserialize)]
struct OutboxMessageRaw {
    subjects: Vec<String>,
    #[serde(default)]
    payload: Option<Box<RawValue>>,
}

fn build_event_text(payload: Option<&RawValue>, strip_internal: bool) -> String {
    let raw = payload.map(|v| v.get()).unwrap_or("null");
    if strip_internal {
        if let Ok(internal) = serde_json::from_str::<InternalMessage>(raw) {
            if let Ok(client_json) = serde_json::to_string(&internal.to_client_payload()) {
                let mut text = String::with_capacity(client_json.len() + 28);
                text.push_str(r#"{"type":"event","payload":"#);
                text.push_str(&client_json);
                text.push('}');
                return text;
            }
        }
    }
    let mut text = String::with_capacity(raw.len() + 28);
    text.push_str(r#"{"type":"event","payload":"#);
    text.push_str(raw);
    text.push('}');
    text
}

pub(crate) struct RabbitPublisher {
    config: RabbitConfig,
    state: Mutex<RabbitPublishState>,
}

impl RabbitPublisher {
    pub(crate) fn new(config: &Config) -> Self {
        Self {
            config: RabbitConfig {
                dsn: config.rabbitmq_dsn.clone(),
                inbox_exchange: config.rabbitmq_inbox_exchange.clone(),
                inbox_routing_key: config.rabbitmq_inbox_routing_key.clone(),
                inbox_queue: config.rabbitmq_inbox_queue.clone(),
                inbox_queue_ttl_ms: config.rabbitmq_inbox_queue_ttl_ms,
                events_exchange: config.rabbitmq_events_exchange.clone(),
                events_routing_key: config.rabbitmq_events_routing_key.clone(),
                events_queue: config.rabbitmq_events_queue.clone(),
                events_queue_ttl_ms: config.rabbitmq_events_queue_ttl_ms,
                dlq_exchange: config.rabbitmq_dlq_exchange.clone(),
                dlq_queue: config.rabbitmq_dlq_queue.clone(),
            },
            state: Mutex::new(RabbitPublishState {
                connection: None,
                channel: None,
            }),
        }
    }

    async fn ensure_channel(&self) -> Option<Channel> {
        {
            let state = self.state.lock().await;
            if let Some(channel) = &state.channel {
                return Some(channel.clone());
            }
        }
        let connection = match Connection::connect(
            &self.config.dsn,
            ConnectionProperties::default(),
        )
        .await
        {
            Ok(conn) => conn,
            Err(err) => {
                warn!("rabbitmq.connect_failed: {err}");
                return None;
            }
        };
        let channel = match connection.create_channel().await {
            Ok(channel) => channel,
            Err(err) => {
                warn!("rabbitmq.channel_failed: {err}");
                return None;
            }
        };
        if let Err(err) = self.declare_topology(&channel).await {
            warn!("rabbitmq.declare_failed: {err}");
        }
        let mut state = self.state.lock().await;
        state.connection = Some(connection);
        state.channel = Some(channel.clone());
        Some(channel)
    }

    async fn declare_topology(&self, channel: &Channel) -> Result<(), lapin::Error> {
        if !self.config.inbox_exchange.is_empty() {
            channel
                .exchange_declare(
                    &self.config.inbox_exchange,
                    ExchangeKind::Direct,
                    ExchangeDeclareOptions { durable: true, ..Default::default() },
                    FieldTable::default(),
                )
                .await?;
        }
        if !self.config.events_exchange.is_empty() {
            channel
                .exchange_declare(
                    &self.config.events_exchange,
                    ExchangeKind::Direct,
                    ExchangeDeclareOptions { durable: true, ..Default::default() },
                    FieldTable::default(),
                )
                .await?;
        }
        if !self.config.dlq_exchange.is_empty() {
            channel
                .exchange_declare(
                    &self.config.dlq_exchange,
                    ExchangeKind::Direct,
                    ExchangeDeclareOptions { durable: true, ..Default::default() },
                    FieldTable::default(),
                )
                .await?;
            if !self.config.dlq_queue.is_empty() {
                channel
                    .queue_declare(
                        &self.config.dlq_queue,
                        QueueDeclareOptions { durable: true, ..Default::default() },
                        FieldTable::default(),
                    )
                    .await?;
                channel
                    .queue_bind(
                        &self.config.dlq_queue,
                        &self.config.dlq_exchange,
                        &self.config.dlq_queue,
                        QueueBindOptions::default(),
                        FieldTable::default(),
                    )
                    .await?;
            }
        }
        if !self.config.inbox_queue.is_empty() {
            let args = rabbit_queue_args(
                self.config.inbox_queue_ttl_ms,
                &self.config.dlq_exchange,
                &self.config.dlq_queue,
            );
            channel
                .queue_declare(
                    &self.config.inbox_queue,
                    QueueDeclareOptions { durable: true, ..Default::default() },
                    args,
                )
                .await?;
            channel
                .queue_bind(
                    &self.config.inbox_queue,
                    &self.config.inbox_exchange,
                    &self.config.inbox_routing_key,
                    QueueBindOptions::default(),
                    FieldTable::default(),
                )
                .await?;
        }
        if !self.config.events_queue.is_empty() {
            let args = rabbit_queue_args(
                self.config.events_queue_ttl_ms,
                &self.config.dlq_exchange,
                &self.config.dlq_queue,
            );
            channel
                .queue_declare(
                    &self.config.events_queue,
                    QueueDeclareOptions { durable: true, ..Default::default() },
                    args,
                )
                .await?;
            channel
                .queue_bind(
                    &self.config.events_queue,
                    &self.config.events_exchange,
                    &self.config.events_routing_key,
                    QueueBindOptions::default(),
                    FieldTable::default(),
                )
                .await?;
        }
        Ok(())
    }

    pub(crate) async fn publish(&self, exchange: &str, routing_key: &str, payload: &Value) -> bool {
        let body = normalize_json(payload.clone());
        let body = serde_json::to_string(&body).unwrap_or_else(|_| "{}".to_string());
        self.publish_raw(exchange, routing_key, body.as_bytes()).await
    }

    pub(crate) async fn publish_raw(&self, exchange: &str, routing_key: &str, body: &[u8]) -> bool {
        if exchange.is_empty() {
            return false;
        }
        let Some(channel) = self.ensure_channel().await else {
            return false;
        };
        let confirm = channel
            .basic_publish(
                exchange,
                routing_key,
                BasicPublishOptions::default(),
                body,
                BasicProperties::default(),
            )
            .await;
        match confirm {
            Ok(confirm) => confirm.await.is_ok(),
            Err(_) => false,
        }
    }
}

fn rabbit_queue_args(ttl_ms: i64, dlq_exchange: &str, dlq_queue: &str) -> FieldTable {
    let mut table = FieldTable::default();
    if ttl_ms > 0 {
        let ttl = ttl_ms.min(u32::MAX as i64) as u32;
        table.insert("x-message-ttl".into(), AMQPValue::LongUInt(ttl));
    }
    if !dlq_exchange.is_empty() {
        table.insert(
            "x-dead-letter-exchange".into(),
            AMQPValue::LongString(LongString::from(dlq_exchange.to_string())),
        );
        if !dlq_queue.is_empty() {
            table.insert(
                "x-dead-letter-routing-key".into(),
                AMQPValue::LongString(LongString::from(dlq_queue.to_string())),
            );
        }
    }
    table
}

pub(crate) async fn redis_outbox_consumer(state: Arc<AppState>) {
    let Some(client) = &state.redis else { return; };
    let mut last_id = if state.config.replay_strategy == "none" {
        "$".to_string()
    } else {
        "0-0".to_string()
    };
    let mut backoff = 1.0;
    loop {
        match client.get_multiplexed_async_connection().await {
            Ok(mut conn) => {
                backoff = 1.0;
                loop {
                    let response: redis::RedisResult<Vec<(String, Vec<(String, HashMap<String, String>)>)>> =
                        redis::cmd("XREAD")
                            .arg("BLOCK")
                            .arg(5000)
                            .arg("COUNT")
                            .arg(10)
                            .arg("STREAMS")
                            .arg(&state.config.redis_stream)
                            .arg(&last_id)
                            .query_async(&mut conn)
                            .await;
                    match response {
                        Ok(streams) => {
                            if streams.is_empty() {
                                continue;
                            }
                            for (_stream, entries) in streams {
                                for (id, fields) in entries {
                                    last_id = id;
                                    if let Some(raw) = fields.get("data") {
                                        if let Ok(value) =
                                            serde_json::from_str::<OutboxMessageRaw>(raw)
                                        {
                                            let text = build_event_text(
                                                value.payload.as_deref(),
                                                state.config.outbox_strip_internal,
                                            );
                                            let stats = state
                                                .connections
                                                .send_text_to_subjects(&value.subjects, &text)
                                                .await;
                                            if stats.sent > 0 {
                                                Metrics::inc(
                                                    &state.metrics.ws_messages_out_total,
                                                    stats.sent as u64,
                                                );
                                            }
                                            if stats.dropped > 0 {
                                                Metrics::inc(
                                                    &state.metrics.backpressure_dropped_total,
                                                    stats.dropped as u64,
                                                );
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        Err(err) => {
                            warn!("redis.outbox.error: {err}");
                            break;
                        }
                    }
                }
            }
            Err(err) => {
                warn!("redis.connect_failed: {err}");
            }
        }
        tokio::time::sleep(Duration::from_secs_f64(backoff)).await;
        backoff = (backoff * 2.0).min(30.0);
    }
}

pub(crate) async fn rabbit_outbox_consumer(state: Arc<AppState>) {
    if state.config.rabbitmq_dsn.is_empty() || state.config.rabbitmq_queue.is_empty() {
        return;
    }
    let mut backoff = 1.0;
    loop {
        match Connection::connect(&state.config.rabbitmq_dsn, ConnectionProperties::default()).await
        {
            Ok(connection) => {
                backoff = 1.0;
                let channel = match connection.create_channel().await {
                    Ok(channel) => channel,
                    Err(err) => {
                        warn!("rabbitmq.channel_failed: {err}");
                        continue;
                    }
                };
                if let Err(err) = channel
                    .exchange_declare(
                        &state.config.rabbitmq_exchange,
                        ExchangeKind::Direct,
                        ExchangeDeclareOptions { durable: true, ..Default::default() },
                        FieldTable::default(),
                    )
                    .await
                {
                    warn!("rabbitmq.exchange_failed: {err}");
                    continue;
                }
                if !state.config.rabbitmq_dlq_exchange.is_empty() {
                    let _ = channel
                        .exchange_declare(
                            &state.config.rabbitmq_dlq_exchange,
                            ExchangeKind::Direct,
                            ExchangeDeclareOptions { durable: true, ..Default::default() },
                            FieldTable::default(),
                        )
                        .await;
                    if !state.config.rabbitmq_dlq_queue.is_empty() {
                        let _ = channel
                            .queue_declare(
                                &state.config.rabbitmq_dlq_queue,
                                QueueDeclareOptions { durable: true, ..Default::default() },
                                FieldTable::default(),
                            )
                            .await;
                        let _ = channel
                            .queue_bind(
                                &state.config.rabbitmq_dlq_queue,
                                &state.config.rabbitmq_dlq_exchange,
                                &state.config.rabbitmq_dlq_queue,
                                QueueBindOptions::default(),
                                FieldTable::default(),
                            )
                            .await;
                    }
                }
                let args = rabbit_queue_args(
                    state.config.rabbitmq_queue_ttl_ms,
                    &state.config.rabbitmq_dlq_exchange,
                    &state.config.rabbitmq_dlq_queue,
                );
                if let Err(err) = channel
                    .queue_declare(
                        &state.config.rabbitmq_queue,
                        QueueDeclareOptions { durable: true, ..Default::default() },
                        args,
                    )
                    .await
                {
                    warn!("rabbitmq.queue_failed: {err}");
                    continue;
                }
                if let Err(err) = channel
                    .queue_bind(
                        &state.config.rabbitmq_queue,
                        &state.config.rabbitmq_exchange,
                        &state.config.rabbitmq_routing_key,
                        QueueBindOptions::default(),
                        FieldTable::default(),
                    )
                    .await
                {
                    warn!("rabbitmq.bind_failed: {err}");
                    continue;
                }

                let consumer = match channel
                    .basic_consume(
                        &state.config.rabbitmq_queue,
                        "rust_gateway_outbox",
                        BasicConsumeOptions::default(),
                        FieldTable::default(),
                    )
                    .await
                {
                    Ok(consumer) => consumer,
                    Err(err) => {
                        warn!("rabbitmq.consume_failed: {err}");
                        continue;
                    }
                };

                let mut consumer = consumer;
                while let Some(delivery) = consumer.next().await {
                    match delivery {
                        Ok(delivery) => {
                            let raw = delivery.data.clone();
                            if let Ok(value) = serde_json::from_slice::<OutboxMessageRaw>(&raw) {
                                let text = build_event_text(
                                    value.payload.as_deref(),
                                    state.config.outbox_strip_internal,
                                );
                                let stats = state
                                    .connections
                                    .send_text_to_subjects(&value.subjects, &text)
                                    .await;
                                if stats.sent > 0 {
                                    Metrics::inc(
                                        &state.metrics.ws_messages_out_total,
                                        stats.sent as u64,
                                    );
                                }
                                if stats.dropped > 0 {
                                    Metrics::inc(
                                        &state.metrics.backpressure_dropped_total,
                                        stats.dropped as u64,
                                    );
                                }
                            } else {
                                push_rabbit_dlq(&channel, &state.config, "parse_error", &raw).await;
                            }
                            let _ = delivery.ack(BasicAckOptions::default()).await;
                        }
                        Err(err) => {
                            warn!("rabbitmq.delivery_failed: {err}");
                            break;
                        }
                    }
                }
            }
            Err(err) => {
                warn!("rabbitmq.connect_failed: {err}");
            }
        }
        tokio::time::sleep(Duration::from_secs_f64(backoff)).await;
        backoff = (backoff * 2.0).min(30.0);
    }
}

async fn push_rabbit_dlq(channel: &Channel, config: &Config, reason: &str, raw: &[u8]) {
    if config.rabbitmq_dlq_exchange.is_empty() || config.rabbitmq_dlq_queue.is_empty() {
        return;
    }
    let _ = channel
        .exchange_declare(
            &config.rabbitmq_dlq_exchange,
            ExchangeKind::Direct,
            ExchangeDeclareOptions { durable: true, ..Default::default() },
            FieldTable::default(),
        )
        .await;
    let _ = channel
        .queue_declare(
            &config.rabbitmq_dlq_queue,
            QueueDeclareOptions { durable: true, ..Default::default() },
            FieldTable::default(),
        )
        .await;
    let _ = channel
        .queue_bind(
            &config.rabbitmq_dlq_queue,
            &config.rabbitmq_dlq_exchange,
            &config.rabbitmq_dlq_queue,
            QueueBindOptions::default(),
            FieldTable::default(),
        )
        .await;
    let mut headers = FieldTable::default();
    headers.insert(
        "reason".into(),
        AMQPValue::LongString(LongString::from(reason.to_string())),
    );
    let props = BasicProperties::default().with_headers(headers);
    if let Ok(confirm) = channel
        .basic_publish(
            &config.rabbitmq_dlq_exchange,
            &config.rabbitmq_dlq_queue,
            BasicPublishOptions::default(),
            raw,
            props,
        )
        .await
    {
        let _ = confirm.await;
    }
}
