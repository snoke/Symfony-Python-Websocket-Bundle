<?php

namespace Snoke\WsBundle\Service;

class PresenceInterpreter
{
    private string $strategy;
    private int $ttlSeconds;
    private int $heartbeatSeconds;
    private int $graceSeconds;
    private bool $useLastSeen;

    public function __construct(array $config)
    {
        $interpretation = $config['interpretation'] ?? [];
        $this->strategy = (string) ($interpretation['strategy'] ?? 'none');
        $this->ttlSeconds = (int) ($interpretation['ttl_seconds'] ?? 120);
        $this->heartbeatSeconds = (int) ($interpretation['heartbeat_seconds'] ?? 30);
        $this->graceSeconds = (int) ($interpretation['grace_seconds'] ?? 15);
        $this->useLastSeen = (bool) ($interpretation['use_last_seen'] ?? true);
    }

    public function filterConnections(array $connections): array
    {
        if ($this->strategy === 'none' || $this->strategy === 'session') {
            return $connections;
        }

        $window = $this->strategy === 'heartbeat' ? $this->heartbeatSeconds : $this->ttlSeconds;
        if ($window <= 0) {
            return $connections;
        }

        $threshold = $window + max(0, $this->graceSeconds);
        $now = time();
        $filtered = [];

        foreach ($connections as $connection) {
            if (!is_array($connection)) {
                continue;
            }
            $timestamp = $this->extractTimestamp($connection);
            if ($timestamp === null) {
                continue;
            }
            if (($now - $timestamp) <= $threshold) {
                $filtered[] = $connection;
            }
        }

        return $filtered;
    }

    private function extractTimestamp(array $connection): ?int
    {
        $candidate = null;
        if ($this->useLastSeen && isset($connection['last_seen_at'])) {
            $candidate = $connection['last_seen_at'];
        }
        if ($candidate === null && isset($connection['connected_at'])) {
            $candidate = $connection['connected_at'];
        }
        if ($candidate === null) {
            return null;
        }
        if (is_numeric($candidate)) {
            return (int) $candidate;
        }
        return null;
    }
}
