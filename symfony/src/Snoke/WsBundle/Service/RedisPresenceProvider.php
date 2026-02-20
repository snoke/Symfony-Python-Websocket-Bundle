<?php

namespace Snoke\WsBundle\Service;

use Predis\Client;
use Snoke\WsBundle\Contract\PresenceProviderInterface;

class RedisPresenceProvider implements PresenceProviderInterface
{
    private Client $client;
    private array $config;

    public function __construct(array $config)
    {
        $this->config = $config;
        $dsn = $config['redis']['dsn'] ?? 'redis://redis:6379';
        $this->client = new Client($dsn);
    }

    public function listConnections(?string $subjectKey = null, ?string $userId = null): array
    {
        $prefix = $this->config['redis']['prefix'] ?? 'presence:';

        if ($userId) {
            return $this->listConnectionsForUser($userId);
        }

        if ($subjectKey) {
            $setKey = $prefix.'subject:'.$subjectKey;
            $ids = $this->client->smembers($setKey) ?: [];
            return ['connections' => $this->hydrateConnections($ids, $prefix)];
        }

        $connections = [];
        $cursor = 0;
        $pattern = $prefix.'conn:*';
        do {
            [$cursor, $keys] = $this->client->scan($cursor, ['match' => $pattern, 'count' => 100]);
            foreach ($keys as $key) {
                $data = $this->client->hgetall($key);
                if (!empty($data)) {
                    $connections[] = $data;
                }
            }
        } while ($cursor !== 0);

        return ['connections' => $connections];
    }

    public function listConnectionsForUser(string $userId): array
    {
        $prefix = $this->config['redis']['prefix'] ?? 'presence:';
        $setKey = $prefix.'user:'.$userId;
        $ids = $this->client->smembers($setKey) ?: [];
        return ['connections' => $this->hydrateConnections($ids, $prefix)];
    }

    private function hydrateConnections(array $ids, string $prefix): array
    {
        $connections = [];
        foreach ($ids as $id) {
            $data = $this->client->hgetall($prefix.'conn:'.$id);
            if (!empty($data)) {
                $connections[] = $data;
            }
        }
        return $connections;
    }
}
