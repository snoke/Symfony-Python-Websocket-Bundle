<?php

namespace Snoke\WsBundle\Contract;

interface PresenceProviderInterface
{
    public function listConnections(?string $subjectKey = null, ?string $userId = null): array;
    public function listConnectionsForUser(string $userId): array;
}
