<?php

namespace Snoke\WsBundle\Event;

class WebsocketMessageReceivedEvent
{
    public function __construct(
        private string $connectionId,
        private string $userId,
        private array $subjects,
        private int $connectedAt,
        private mixed $message,
        private string $raw
    ) {}

    public function getConnectionId(): string
    {
        return $this->connectionId;
    }

    public function getUserId(): string
    {
        return $this->userId;
    }

    public function getSubjects(): array
    {
        return $this->subjects;
    }

    public function getConnectedAt(): int
    {
        return $this->connectedAt;
    }

    public function getMessage(): mixed
    {
        return $this->message;
    }

    public function getRaw(): string
    {
        return $this->raw;
    }
}
