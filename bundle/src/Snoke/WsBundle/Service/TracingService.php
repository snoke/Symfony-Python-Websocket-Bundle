<?php

namespace Snoke\WsBundle\Service;

use OpenTelemetry\API\Signals;
use OpenTelemetry\API\Trace\SpanKind;
use OpenTelemetry\API\Trace\TracerInterface;
use OpenTelemetry\API\Trace\Propagation\TraceContextPropagator;
use OpenTelemetry\Contrib\Grpc\GrpcTransportFactory;
use OpenTelemetry\Contrib\Otlp\OtlpHttpTransportFactory;
use OpenTelemetry\Contrib\Otlp\OtlpUtil;
use OpenTelemetry\Contrib\Otlp\SpanExporter;
use OpenTelemetry\SDK\Resource\ResourceInfo;
use OpenTelemetry\SDK\Trace\SpanExporter\ConsoleSpanExporterFactory;
use OpenTelemetry\SDK\Trace\SpanProcessor\BatchSpanProcessor;
use OpenTelemetry\SDK\Trace\SpanProcessor\SimpleSpanProcessor;
use OpenTelemetry\SDK\Trace\TracerProvider;
use OpenTelemetry\SemConv\ResourceAttributes;

class TracingService
{
    private bool $enabled;
    private string $traceparentField;
    private string $traceIdField;
    private ?TracerInterface $tracer = null;
    private ?TracerProvider $provider = null;

    public function __construct(array $config)
    {
        $this->enabled = (bool) ($config['enabled'] ?? false);
        $this->traceparentField = (string) ($config['traceparent_field'] ?? 'traceparent');
        $this->traceIdField = (string) ($config['trace_id_field'] ?? 'trace_id');

        if (!$this->enabled) {
            return;
        }

        if (!class_exists(TracerProvider::class)) {
            $this->enabled = false;
            return;
        }

        $serviceName = (string) ($config['service_name'] ?? 'symfony');
        $exporter = (string) ($config['exporter'] ?? 'stdout');
        $otlpEndpoint = (string) ($config['otlp_endpoint'] ?? '');
        $otlpProtocol = (string) ($config['otlp_protocol'] ?? 'grpc');

        $resource = ResourceInfo::create([ResourceAttributes::SERVICE_NAME => $serviceName]);
        $spanProcessor = $this->buildSpanProcessor($exporter, $otlpEndpoint, $otlpProtocol);
        if ($spanProcessor === null) {
            $this->enabled = false;
            return;
        }

        $this->provider = new TracerProvider($spanProcessor, null, $resource);
        $this->tracer = $this->provider->getTracer('snoke-ws');
    }

    public function isEnabled(): bool
    {
        return $this->enabled && $this->tracer !== null;
    }

    public function getTraceparentField(): string
    {
        return $this->traceparentField;
    }

    public function getTraceIdField(): string
    {
        return $this->traceIdField;
    }

    public function startSpan(
        string $name,
        int $kind = SpanKind::KIND_INTERNAL,
        array $attributes = [],
        ?string $traceparent = null
    ): ?TracingScope {
        if (!$this->isEnabled()) {
            return null;
        }

        $builder = $this->tracer->spanBuilder($name)->setSpanKind($kind);
        if ($traceparent) {
            $context = TraceContextPropagator::getInstance()->extract([
                TraceContextPropagator::TRACEPARENT => $traceparent,
            ]);
            $builder->setParent($context);
        }
        if ($attributes) {
            $builder->setAttributes($attributes);
        }
        $span = $builder->startSpan();
        $scope = $span->activate();

        return new TracingScope($span, $scope);
    }

    public function injectTraceparent(array &$carrier): void
    {
        if (!$this->isEnabled()) {
            return;
        }
        TraceContextPropagator::getInstance()->inject($carrier);
    }

    public function currentTraceparent(): string
    {
        $carrier = [];
        $this->injectTraceparent($carrier);
        return isset($carrier[TraceContextPropagator::TRACEPARENT])
            ? (string) $carrier[TraceContextPropagator::TRACEPARENT]
            : '';
    }

    private function buildSpanProcessor(string $exporter, string $otlpEndpoint, string $otlpProtocol): ?object
    {
        if ($exporter === 'none') {
            return null;
        }

        if ($exporter === 'otlp' && $otlpEndpoint !== '') {
            try {
                $transport = $this->createOtlpTransport($otlpEndpoint, $otlpProtocol);
                $spanExporter = new SpanExporter($transport);
                return new BatchSpanProcessor($spanExporter);
            } catch (\Throwable) {
                // fall through to console exporter
            }
        }

        return new SimpleSpanProcessor((new ConsoleSpanExporterFactory())->create());
    }

    private function createOtlpTransport(string $endpoint, string $protocol)
    {
        $protocol = strtolower($protocol);
        if (str_starts_with($protocol, 'grpc')) {
            $path = OtlpUtil::path(Signals::TRACE, 'grpc');
            return (new GrpcTransportFactory())->create($endpoint . $path);
        }
        $path = OtlpUtil::path(Signals::TRACE, 'http/protobuf');
        $headers = OtlpUtil::getHeaders(Signals::TRACE);
        return (new OtlpHttpTransportFactory())->create(
            $endpoint . $path,
            'application/x-protobuf',
            $headers
        );
    }
}
