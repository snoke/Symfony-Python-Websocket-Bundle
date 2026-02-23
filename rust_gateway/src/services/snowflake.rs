use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub(crate) struct SnowflakeGenerator {
    inner: Mutex<SnowflakeState>,
}

struct SnowflakeState {
    epoch_ms: i64,
    worker_id: u16,
    last_ts: i64,
    sequence: u16,
}

impl SnowflakeGenerator {
    pub(crate) fn new(worker_id: u16, epoch_ms: i64) -> Self {
        Self {
            inner: Mutex::new(SnowflakeState {
                epoch_ms,
                worker_id,
                last_ts: -1,
                sequence: 0,
            }),
        }
    }

    pub(crate) fn next_id(&self) -> u64 {
        let mut state = self.inner.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        let mut now = current_time_ms();
        if now < state.last_ts {
            now = state.last_ts;
        }
        if now == state.last_ts {
            state.sequence = (state.sequence + 1) & 0x0fff;
            if state.sequence == 0 {
                now = wait_next_ms(state.last_ts);
            }
        } else {
            state.sequence = 0;
        }
        state.last_ts = now;
        let ts_part = (now - state.epoch_ms) as u64;
        (ts_part << 22) | ((state.worker_id as u64) << 12) | (state.sequence as u64)
    }

    pub(crate) fn next_id_string(&self) -> String {
        self.next_id().to_string()
    }
}

fn current_time_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|_| Duration::from_secs(0))
        .as_millis() as i64
}

fn wait_next_ms(last_ts: i64) -> i64 {
    let mut now = current_time_ms();
    while now <= last_ts {
        std::thread::yield_now();
        now = current_time_ms();
    }
    now
}
