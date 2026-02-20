<?php

namespace Snoke\WsBundle\Service;

use Symfony\Contracts\HttpClient\HttpClientInterface;
use Snoke\WsBundle\Contract\PresenceProviderInterface;

class HttpPresenceProvider implements PresenceProviderInterface
{
    public function __construct(
        private HttpClientInterface $client,
        private array $config
    ) {}

    public function listConnections(?string $subjectKey = null, ?string $userId = null): array
    {
        $http = $this->config['http'];
        $query = [];
        if ($subjectKey) {
            $query['subject'] = $subjectKey;
        }
        if ($userId) {
            $query['user_id'] = $userId;
        }
        $response = $this->client->request('GET', rtrim($http['base_url'], '/').$http['list_path'], [
            'query' => $query,
            'timeout' => $http['timeout_seconds'],
        ]);
        return $response->toArray(false);
    }

    public function listConnectionsForUser(string $userId): array
    {
        $http = $this->config['http'];
        $path = str_replace('{user_id}', $userId, $http['by_user_path']);
        $response = $this->client->request('GET', rtrim($http['base_url'], '/').$path, [
            'timeout' => $http['timeout_seconds'],
        ]);
        return $response->toArray(false);
    }
}
