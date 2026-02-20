<?php

namespace Snoke\WsBundle\Service;

use Snoke\WsBundle\Contract\PublisherInterface;
use Snoke\WsBundle\Contract\SubjectKeyResolverInterface;

class WebsocketPublisher
{
    public function __construct(
        private PublisherInterface $publisher,
        private SubjectKeyResolverInterface $resolver
    ) {}

    public function send(array $subjects, mixed $payload): void
    {
        $keys = [];
        foreach ($subjects as $subject) {
            $keys[] = $this->resolver->resolve($subject);
        }
        $this->publisher->publish($keys, $payload);
    }
}
