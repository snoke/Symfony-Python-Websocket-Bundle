<?php

namespace Snoke\WsBundle\Service;

use Symfony\Contracts\HttpClient\HttpClientInterface;
use Snoke\WsBundle\Contract\PublisherInterface;
use Snoke\WsBundle\Service\TracingService;
use OpenTelemetry\API\Trace\SpanKind;

class HttpPublisher implements PublisherInterface
{
    public function __construct(
        private HttpClientInterface $client,
        private array $config,
        private TracingService $tracing
    ) {}

    public function publish(array $subjectKeys, mixed $payload): void
    {
        $http = $this->config['http'];
        $auth = $http['auth'] ?? ['type' => 'none'];

        $body = [
            'subjects' => $subjectKeys,
            'payload' => $payload,
        ];

        if (($auth['type'] ?? 'none') === 'api_key') {
            $body['api_key'] = $auth['value'] ?? '';
        }

        $headers = [];
        $scope = $this->tracing->startSpan('ws.publish.http', SpanKind::KIND_PRODUCER, [
            'ws.subjects_count' => count($subjectKeys),
        ]);
        $this->tracing->injectTraceparent($headers);
        if (isset($headers['traceparent'])) {
            $body['traceparent'] = $headers['traceparent'];
        }
        try {
            $this->client->request('POST', rtrim($http['base_url'], '/').$http['publish_path'], [
                'json' => $body,
                'timeout' => $http['timeout_seconds'],
                'headers' => $headers,
            ]);
        } finally {
            if ($scope) {
                $scope->end();
            }
        }
    }
}
