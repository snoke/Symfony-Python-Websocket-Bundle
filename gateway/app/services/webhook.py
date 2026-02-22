import asyncio
import hashlib
import hmac
import json
from typing import Any, Dict, Optional

import httpx
from opentelemetry import propagate

from .logging_service import LoggingService
from .metrics import MetricsService
from .settings import Settings
from .tracing import TracingService


class WebhookService:
    def __init__(
        self,
        settings: Settings,
        metrics: MetricsService,
        tracing: TracingService,
        logger: LoggingService,
    ) -> None:
        self._settings = settings
        self._metrics = metrics
        self._tracing = tracing
        self._logger = logger
        self._client: Optional[httpx.AsyncClient] = None

    async def startup(self) -> None:
        if self._settings.EVENTS_MODE in ("webhook", "both") and self._settings.SYMFONY_WEBHOOK_URL:
            self._client = httpx.AsyncClient(timeout=self._settings.WEBHOOK_TIMEOUT_SECONDS)

    async def shutdown(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def post(self, event_type: str, payload: Dict[str, Any], body: Optional[str] = None) -> None:
        if self._settings.EVENTS_MODE not in ("webhook", "both"):
            return
        if not self._settings.SYMFONY_WEBHOOK_URL or not self._client:
            return
        if body is None:
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        headers: Dict[str, str] = {}
        if self._settings.SYMFONY_WEBHOOK_SECRET:
            signature = hmac.new(
                self._settings.SYMFONY_WEBHOOK_SECRET.encode("utf-8"),
                body.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"
        trace_id = payload.get(self._settings.TRACING_TRACE_ID_FIELD)
        if trace_id and self._settings.TRACING_HEADER_NAME:
            headers[self._settings.TRACING_HEADER_NAME] = str(trace_id)
        carrier: Dict[str, str] = {}
        propagate.inject(carrier)
        if "traceparent" in carrier:
            headers["traceparent"] = carrier["traceparent"]
        elif "traceparent" in payload:
            headers["traceparent"] = str(payload["traceparent"])
        for attempt in range(self._settings.WEBHOOK_RETRY_ATTEMPTS):
            try:
                await self._client.post(self._settings.SYMFONY_WEBHOOK_URL, content=body, headers=headers)
                self._metrics.inc("webhook_publish_total")
                return
            except Exception:
                await asyncio.sleep(self._settings.WEBHOOK_RETRY_BASE_SECONDS * (2**attempt))
        self._metrics.inc("webhook_publish_failed_total")
        self._logger.log(
            "webhook_failed",
            type=event_type,
            connection_id=payload.get("connection_id"),
            user_id=payload.get("user_id"),
        )
