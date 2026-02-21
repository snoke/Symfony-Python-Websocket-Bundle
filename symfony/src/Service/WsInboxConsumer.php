<?php

namespace App\Service;

use Predis\Client;
use Psr\Log\LoggerInterface;
use Snoke\WsBundle\Service\TracingService;
use OpenTelemetry\API\Trace\SpanKind;

class WsInboxConsumer
{
    private int $minLevel;

    public function __construct(
        private MessageInbox $inbox,
        private LoggerInterface $logger,
        private TracingService $tracing
    ) {
        $this->minLevel = $this->parseLevel($_ENV['WS_CONSUMER_LOG_LEVEL'] ?? 'info');
    }

    public function run(): void
    {
        $dsn = $_ENV['DEMO_INBOX_REDIS_DSN']
            ?? $_ENV['WS_REDIS_DSN']
            ?? $_ENV['REDIS_DSN']
            ?? '';
        if ($dsn === '') {
            $this->logger->error('ws.inbox.missing_redis_dsn');
            return;
        }

        $stream = $_ENV['DEMO_INBOX_REDIS_STREAM']
            ?? $_ENV['WS_REDIS_INBOX_STREAM']
            ?? $_ENV['REDIS_INBOX_STREAM']
            ?? 'ws.inbox';

        $client = new Client($dsn);

        $lastId = '$';
        $latest = $client->xrevrange($stream, '+', '-', 1);
        foreach ($this->normalizeEntries($latest) as [$entryId, $fields]) {
            $lastId = (string) $entryId;
            $this->handleMessage($fields);
            break;
        }

        $this->logInfo('ws.inbox.consumer_started', [
            'stream' => $stream,
            'last_id' => $lastId,
        ]);

        while (true) {
            try {
                $response = null;
                set_error_handler(static function (): bool {
                    return true;
                });
                try {
                    $response = $client->xread(10, 5000, [$stream], $lastId);
                } finally {
                    restore_error_handler();
                }
                if (!$response || !isset($response[$stream]) || !is_array($response[$stream])) {
                    continue;
                }
                foreach ($this->normalizeEntries($response[$stream]) as [$entryId, $fields]) {
                    $entryId = (string) $entryId;
                    $this->handleMessage($fields);
                    $lastId = $entryId;
                }
            } catch (\Throwable $e) {
                $this->logger->error('ws.inbox.consume_error: '.$e->getMessage());
                sleep(1);
            }
        }
    }

    private function handleMessage(array $fields): void
    {
        $raw = $fields['data'] ?? '';
        if (!is_string($raw) || $raw === '') {
            return;
        }
        $event = json_decode($raw, true);
        if (!is_array($event)) {
            return;
        }
        if (($event['type'] ?? '') !== 'message_received') {
            return;
        }
        $traceparentField = $this->tracing->getTraceparentField();
        $traceIdField = $this->tracing->getTraceIdField();
        $payload = [
            'connection_id' => $event['connection_id'] ?? null,
            'user_id' => $event['user_id'] ?? null,
            'subjects' => $event['subjects'] ?? [],
            'connected_at' => $event['connected_at'] ?? null,
            'message' => $event['message'] ?? null,
            'raw' => $event['raw'] ?? null,
            'trace_id' => $event[$traceIdField] ?? null,
            'traceparent' => $event[$traceparentField] ?? null,
            'received_at' => time(),
        ];

        $scope = $this->tracing->startSpan('ws.inbox.consume', SpanKind::KIND_CONSUMER, [
            'ws.connection_id' => (string) ($payload['connection_id'] ?? ''),
            'ws.user_id' => (string) ($payload['user_id'] ?? ''),
        ], is_string($payload['traceparent']) ? $payload['traceparent'] : null);

        try {
            $this->inbox->setLastMessage($payload);
            $this->logInfo('ws.inbox.message_received', $payload);
        } finally {
            if ($scope) {
                $scope->end();
            }
        }
    }

    /**
     * @return array<int, array{0: string, 1: array}>
     */
    private function normalizeEntries(mixed $entries): array
    {
        if (!is_array($entries)) {
            return [];
        }
        $normalized = [];
        foreach ($entries as $key => $value) {
            if (is_array($value) && array_key_exists(0, $value) && array_key_exists(1, $value)) {
                $normalized[] = [$value[0], $value[1]];
                continue;
            }
            if (is_string($key) && is_array($value)) {
                $normalized[] = [$key, $value];
            }
        }
        return $normalized;
    }

    private function logInfo(string $message, array $context = []): void
    {
        if ($this->minLevel <= 200) {
            $this->logger->info($message, $context);
        }
    }

    private function parseLevel(string $level): int
    {
        $level = strtolower($level);
        return match ($level) {
            'debug' => 100,
            'info' => 200,
            'notice' => 250,
            'warning' => 300,
            'error' => 400,
            'critical' => 500,
            'alert' => 550,
            'emergency' => 600,
            default => 200,
        };
    }
}
