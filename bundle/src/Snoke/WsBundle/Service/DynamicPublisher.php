<?php

namespace Snoke\WsBundle\Service;

use Snoke\WsBundle\Contract\PublisherInterface;

class DynamicPublisher implements PublisherInterface
{
    public function __construct(
        private PublisherInterface $httpPublisher,
        private PublisherInterface $redisStreamPublisher,
        private PublisherInterface $rabbitPublisher,
        private array $transportConfig
    ) {}

    public function publish(array $subjects, mixed $payload): void
    {
        $type = $this->transportConfig['type'] ?? 'http';
        if ($type === 'redis_stream') {
            $this->redisStreamPublisher->publish($subjects, $payload);
            return;
        }
        if ($type === 'rabbitmq') {
            $this->rabbitPublisher->publish($subjects, $payload);
            return;
        }
        $this->httpPublisher->publish($subjects, $payload);
    }
}
