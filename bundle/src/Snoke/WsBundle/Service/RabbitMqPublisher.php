<?php

namespace Snoke\WsBundle\Service;

use PhpAmqpLib\Connection\AMQPStreamConnection;
use PhpAmqpLib\Message\AMQPMessage;
use Snoke\WsBundle\Contract\PublisherInterface;
use Snoke\WsBundle\Service\TracingService;
use OpenTelemetry\API\Trace\SpanKind;

class RabbitMqPublisher implements PublisherInterface
{
    private array $config;
    private TracingService $tracing;

    public function __construct(array $config, TracingService $tracing)
    {
        $this->config = $config;
        $this->tracing = $tracing;
    }

    public function publish(array $subjectKeys, mixed $payload): void
    {
        $dsn = $this->config['rabbitmq']['dsn'] ?? 'amqp://guest:guest@rabbitmq:5672/';
        $exchange = $this->config['rabbitmq']['exchange'] ?? 'ws.outbox';
        $queue = $this->config['rabbitmq']['queue'] ?? 'ws.outbox';
        $routingKey = $this->config['rabbitmq']['routing_key'] ?? 'ws.outbox';

        $parts = parse_url($dsn);
        $host = $parts['host'] ?? 'rabbitmq';
        $port = $parts['port'] ?? 5672;
        $user = $parts['user'] ?? 'guest';
        $pass = $parts['pass'] ?? 'guest';
        $vhost = isset($parts['path']) ? ltrim($parts['path'], '/') : '/';

        $connection = new AMQPStreamConnection($host, $port, $user, $pass, $vhost);
        $channel = $connection->channel();

        $channel->exchange_declare($exchange, 'direct', false, true, false);
        $channel->queue_declare($queue, false, true, false, false);
        $channel->queue_bind($queue, $exchange, $routingKey);

        $bodyPayload = ['subjects' => $subjectKeys, 'payload' => $payload];
        $carrier = [];
        $scope = $this->tracing->startSpan('ws.publish.rabbitmq', SpanKind::KIND_PRODUCER, [
            'ws.subjects_count' => count($subjectKeys),
        ]);
        $this->tracing->injectTraceparent($carrier);
        if (isset($carrier['traceparent'])) {
            $bodyPayload['traceparent'] = $carrier['traceparent'];
        }
        try {
            $body = json_encode($bodyPayload, JSON_UNESCAPED_UNICODE);
            $message = new AMQPMessage($body, ['content_type' => 'application/json', 'delivery_mode' => 2]);
            $channel->basic_publish($message, $exchange, $routingKey);
        } finally {
            $channel->close();
            $connection->close();
            if ($scope) {
                $scope->end();
            }
        }
    }
}
