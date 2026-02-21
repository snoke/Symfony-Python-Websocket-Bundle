<?php

namespace Snoke\WsBundle\Service;

use Predis\Client;
use Snoke\WsBundle\Contract\PublisherInterface;
use Snoke\WsBundle\Service\TracingService;
use OpenTelemetry\API\Trace\SpanKind;

class RedisStreamPublisher implements PublisherInterface
{
    private Client $client;
    private array $config;
    private TracingService $tracing;

    public function __construct(array $config, TracingService $tracing)
    {
        $this->config = $config;
        $dsn = $config['redis_stream']['dsn'] ?? 'redis://redis:6379';
        $this->client = new Client($dsn);
        $this->tracing = $tracing;
    }

    public function publish(array $subjectKeys, mixed $payload): void
    {
        $stream = $this->config['redis_stream']['stream'] ?? 'ws.outbox';
        $body = ['subjects' => $subjectKeys, 'payload' => $payload];
        $carrier = [];
        $scope = $this->tracing->startSpan('ws.publish.redis', SpanKind::KIND_PRODUCER, [
            'ws.subjects_count' => count($subjectKeys),
        ]);
        $this->tracing->injectTraceparent($carrier);
        if (isset($carrier['traceparent'])) {
            $body['traceparent'] = $carrier['traceparent'];
        }
        try {
            $data = json_encode($body, JSON_UNESCAPED_UNICODE);
            $this->client->xadd($stream, '*', ['data' => $data]);
        } finally {
            if ($scope) {
                $scope->end();
            }
        }
    }
}
