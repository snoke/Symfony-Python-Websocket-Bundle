import random
from typing import Any, Dict, Optional

from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as OtlpHttpSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.trace import format_trace_id

from .settings import Settings


class TracingService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.tracer = trace.get_tracer("gateway")
        self.enabled = False

    def _create_otlp_exporter(self):
        if self._settings.OTEL_EXPORTER_OTLP_PROTOCOL.startswith("grpc"):
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter as OtlpGrpcSpanExporter,
            )

            return OtlpGrpcSpanExporter(endpoint=self._settings.OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True)
        return OtlpHttpSpanExporter(endpoint=self._settings.OTEL_EXPORTER_OTLP_ENDPOINT)

    def init_tracing(self) -> None:
        if self._settings.TRACING_STRATEGY == "none" or self._settings.TRACING_EXPORTER == "none":
            return
        resource = Resource.create({"service.name": self._settings.OTEL_SERVICE_NAME})
        provider = TracerProvider(resource=resource)
        if self._settings.TRACING_EXPORTER == "otlp" and self._settings.OTEL_EXPORTER_OTLP_ENDPOINT:
            exporter = self._create_otlp_exporter()
            provider.add_span_processor(BatchSpanProcessor(exporter))
        else:
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        self.tracer = trace.get_tracer("gateway")
        self.enabled = True

    def should_sample(self) -> bool:
        if self._settings.TRACING_SAMPLE_RATE <= 0:
            return False
        if self._settings.TRACING_SAMPLE_RATE >= 1:
            return True
        return random.random() < self._settings.TRACING_SAMPLE_RATE

    def should_record(self, has_parent: bool) -> bool:
        if self._settings.TRACING_STRATEGY == "none":
            return False
        if self._settings.TRACING_STRATEGY == "propagate" and not has_parent:
            return False
        return self.should_sample()

    def extract_traceparent(self, data: Optional[Dict[str, Any]]) -> str:
        if not data:
            return ""
        traceparent = data.get("traceparent")
        if traceparent is None and isinstance(data.get("meta"), dict):
            traceparent = data["meta"].get("traceparent")
        return str(traceparent) if traceparent else ""

    def extract_trace_id(self, data: Optional[Dict[str, Any]]) -> str:
        if not data:
            return ""
        trace_id = data.get(self._settings.TRACING_TRACE_ID_FIELD)
        if trace_id is None and isinstance(data.get("meta"), dict):
            trace_id = data["meta"].get(self._settings.TRACING_TRACE_ID_FIELD)
        return str(trace_id) if trace_id else ""

    def extract_context(self, traceparent: str):
        if not traceparent:
            return None
        return propagate.extract({"traceparent": traceparent})

    def inject_trace_context(self, payload: Dict[str, Any]) -> None:
        carrier: Dict[str, str] = {}
        propagate.inject(carrier)
        traceparent = carrier.get("traceparent")
        if traceparent:
            payload["traceparent"] = traceparent
        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            if self._settings.TRACING_TRACE_ID_FIELD not in payload or not payload.get(
                self._settings.TRACING_TRACE_ID_FIELD
            ):
                payload[self._settings.TRACING_TRACE_ID_FIELD] = format_trace_id(
                    span.get_span_context().trace_id
                )
