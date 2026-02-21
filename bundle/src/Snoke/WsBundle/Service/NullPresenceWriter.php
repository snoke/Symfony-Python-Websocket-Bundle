<?php

namespace Snoke\WsBundle\Service;

use Snoke\WsBundle\Contract\PresenceWriterInterface;

class NullPresenceWriter implements PresenceWriterInterface
{
    public function upsertConnection(string $connectionId, string $userId, array $subjects, int $connectedAt): void
    {
    }

    public function touchConnection(string $connectionId, string $userId, array $subjects): void
    {
    }

    public function removeConnection(string $connectionId, string $userId, array $subjects): void
    {
    }
}
