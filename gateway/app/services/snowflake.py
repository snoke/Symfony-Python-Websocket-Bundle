import threading
import time


class SnowflakeGenerator:
    def __init__(self, worker_id: int, epoch_ms: int) -> None:
        self._worker_id = worker_id & 0x03FF
        self._epoch_ms = epoch_ms
        self._lock = threading.Lock()
        self._last_ts = -1
        self._sequence = 0

    def next_id(self) -> int:
        with self._lock:
            now = self._current_time_ms()
            if now < self._last_ts:
                now = self._last_ts
            if now == self._last_ts:
                self._sequence = (self._sequence + 1) & 0x0FFF
                if self._sequence == 0:
                    now = self._wait_next_ms(self._last_ts)
            else:
                self._sequence = 0
            self._last_ts = now
            ts_part = now - self._epoch_ms
            return (ts_part << 22) | (self._worker_id << 12) | self._sequence

    def next_id_str(self) -> str:
        return str(self.next_id())

    @staticmethod
    def _current_time_ms() -> int:
        return int(time.time() * 1000)

    def _wait_next_ms(self, last_ts: int) -> int:
        now = self._current_time_ms()
        while now <= last_ts:
            time.sleep(0)
            now = self._current_time_ms()
        return now
