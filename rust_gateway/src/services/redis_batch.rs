use std::sync::Arc;
use std::time::Duration;

use tokio::sync::mpsc;
use tracing::warn;

use crate::services::metrics::Metrics;

pub(crate) struct RedisBatcher {
    tx: mpsc::Sender<RedisBatchItem>,
}

struct RedisBatchItem {
    stream: String,
    data: Vec<u8>,
    maxlen: Option<usize>,
}

impl RedisBatcher {
    pub(crate) fn new(
        client: redis::Client,
        metrics: Arc<Metrics>,
        max_batch: usize,
        interval: Duration,
        queue_size: usize,
    ) -> Self {
        let max_batch = max_batch.max(1);
        let queue_size = queue_size.max(1);
        let interval = if interval.is_zero() {
            Duration::from_millis(1)
        } else {
            interval
        };
        let (tx, mut rx) = mpsc::channel::<RedisBatchItem>(queue_size);
        tokio::spawn(async move {
            let mut batch: Vec<RedisBatchItem> = Vec::with_capacity(max_batch);
            let mut ticker = tokio::time::interval(interval);
            loop {
                tokio::select! {
                    item = rx.recv() => {
                        match item {
                            Some(item) => {
                                batch.push(item);
                                if batch.len() >= max_batch {
                                    flush_batch(&client, &metrics, &mut batch).await;
                                }
                            }
                            None => {
                                break;
                            }
                        }
                    }
                    _ = ticker.tick() => {
                        if !batch.is_empty() {
                            flush_batch(&client, &metrics, &mut batch).await;
                        }
                    }
                }
            }
            if !batch.is_empty() {
                flush_batch(&client, &metrics, &mut batch).await;
            }
        });
        Self { tx }
    }

    pub(crate) fn enqueue(
        &self,
        stream: String,
        data: Vec<u8>,
        maxlen: Option<usize>,
    ) -> bool {
        self.tx
            .try_send(RedisBatchItem {
                stream,
                data,
                maxlen,
            })
            .is_ok()
    }
}

async fn flush_batch(client: &redis::Client, metrics: &Metrics, batch: &mut Vec<RedisBatchItem>) {
    if batch.is_empty() {
        return;
    }
    match client.get_multiplexed_async_connection().await {
        Ok(mut conn) => {
            let mut pipe = redis::pipe();
            for item in batch.iter() {
                let mut cmd = pipe.cmd("XADD");
                cmd.arg(&item.stream);
                if let Some(maxlen) = item.maxlen {
                    cmd.arg("MAXLEN").arg("~").arg(maxlen);
                }
                cmd.arg("*").arg("data").arg(&item.data);
            }
            let result: redis::RedisResult<()> = pipe.query_async(&mut conn).await;
            if result.is_ok() {
                Metrics::inc(&metrics.broker_publish_total, batch.len() as u64);
            } else if let Err(err) = result {
                warn!("redis.batch_publish_failed: {err}");
            }
        }
        Err(err) => {
            warn!("redis.connect_failed: {err}");
        }
    }
    batch.clear();
}
