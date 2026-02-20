<?php

namespace Snoke\WsBundle\Event;

use Symfony\Contracts\EventDispatcher\Event;

class WebsocketConnectionClosedEvent extends Event
{
    public function __construct(
        public string $connectionId,
        public string $userId,
        public array $subjects,
        public int $connectedAt
    ) {}
}
