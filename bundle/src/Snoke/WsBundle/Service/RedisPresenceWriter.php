<?php

namespace Snoke\WsBundle\Service;

use Predis\Client;
use Snoke\WsBundle\Contract\PresenceWriterInterface;

class RedisPresenceWriter implements PresenceWriterInterface
{
    private Client $client;
    private string $prefix;
    private int $ttlSeconds;

    public function __construct(array $config)
    {
        $dsn = $config['redis']['dsn'] ?? 'redis://redis:6379';
        $this->client = new Client($dsn);
        $this->prefix = $config['redis']['prefix'] ?? 'presence:';
        $this->ttlSeconds = (int) ($config['writer']['ttl_seconds'] ?? 120);
    }

    public function upsertConnection(string $connectionId, string $userId, array $subjects, int $connectedAt): void
    {
        $now = time();
        $connKey = $this->prefix.'conn:'.$connectionId;
        $this->client->hset($connKey, [
            'connection_id' => $connectionId,
            'user_id' => $userId,
            'subjects' => json_encode($subjects),
            'connected_at' => (string) $connectedAt,
            'last_seen_at' => (string) $now,
        ]);
        $this->applyTtl($connKey);

        $userKey = $this->prefix.'user:'.$userId;
        $this->client->sadd($userKey, [$connectionId]);
        $this->applyTtl($userKey);

        foreach ($subjects as $subject) {
            $subjectKey = $this->prefix.'subject:'.$subject;
            $this->client->sadd($subjectKey, [$connectionId]);
            $this->applyTtl($subjectKey);
        }
    }

    public function touchConnection(string $connectionId, string $userId, array $subjects): void
    {
        $connKey = $this->prefix.'conn:'.$connectionId;
        $this->client->hset($connKey, [
            'last_seen_at' => (string) time(),
        ]);
        $this->applyTtl($connKey);

        $userKey = $this->prefix.'user:'.$userId;
        $this->applyTtl($userKey);

        foreach ($subjects as $subject) {
            $this->applyTtl($this->prefix.'subject:'.$subject);
        }
    }

    public function removeConnection(string $connectionId, string $userId, array $subjects): void
    {
        $this->client->del([$this->prefix.'conn:'.$connectionId]);
        $this->client->srem($this->prefix.'user:'.$userId, [$connectionId]);
        foreach ($subjects as $subject) {
            $this->client->srem($this->prefix.'subject:'.$subject, [$connectionId]);
        }
    }

    private function applyTtl(string $key): void
    {
        if ($this->ttlSeconds > 0) {
            $this->client->expire($key, $this->ttlSeconds);
        }
    }
}
