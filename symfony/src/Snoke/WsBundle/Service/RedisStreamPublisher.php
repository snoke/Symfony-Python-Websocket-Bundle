<?php

namespace Snoke\WsBundle\Service;

use Predis\Client;
use Snoke\WsBundle\Contract\PublisherInterface;

class RedisStreamPublisher implements PublisherInterface
{
    private Client $client;
    private array $config;

    public function __construct(array $config)
    {
        $this->config = $config;
        $dsn = $config['redis_stream']['dsn'] ?? 'redis://redis:6379';
        $this->client = new Client($dsn);
    }

    public function publish(array $subjectKeys, mixed $payload): void
    {
        $stream = $this->config['redis_stream']['stream'] ?? 'ws.outbox';
        $data = json_encode(['subjects' => $subjectKeys, 'payload' => $payload], JSON_UNESCAPED_UNICODE);
        $this->client->xadd($stream, '*', ['data' => $data]);
    }
}
