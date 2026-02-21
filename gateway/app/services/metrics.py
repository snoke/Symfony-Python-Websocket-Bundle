from typing import Dict


class MetricsService:
    def __init__(self) -> None:
        self._metrics: Dict[str, int] = {
            "ws_connections_total": 0,
            "ws_disconnects_total": 0,
            "ws_messages_total": 0,
            "ws_rate_limited_total": 0,
            "publish_total": 0,
            "broker_publish_total": 0,
            "webhook_publish_total": 0,
            "webhook_publish_failed_total": 0,
            "rabbitmq_replay_total": 0,
            "replay_api_requests_total": 0,
            "replay_api_denied_total": 0,
            "replay_api_rate_limited_total": 0,
            "replay_api_idempotent_total": 0,
            "replay_api_success_total": 0,
            "replay_api_errors_total": 0,
            "backpressure_dropped_total": 0,
            "backpressure_closed_total": 0,
            "backpressure_buffered_total": 0,
        }

    def inc(self, key: str, amount: int = 1) -> None:
        self._metrics[key] = self._metrics.get(key, 0) + amount

    def add(self, key: str, amount: int) -> None:
        self.inc(key, amount)

    def get(self, key: str) -> int:
        return self._metrics.get(key, 0)

    def snapshot(self) -> Dict[str, int]:
        return dict(self._metrics)

    def to_prometheus(self) -> str:
        lines = [f"{key} {value}" for key, value in self._metrics.items()]
        return "\n".join(lines) + "\n"
