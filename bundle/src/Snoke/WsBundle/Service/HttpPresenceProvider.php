<?php

namespace Snoke\WsBundle\Service;

use Symfony\Contracts\HttpClient\HttpClientInterface;
use Snoke\WsBundle\Contract\PresenceProviderInterface;
use Snoke\WsBundle\Service\PresenceInterpreter;

class HttpPresenceProvider implements PresenceProviderInterface
{
    private PresenceInterpreter $interpreter;

    public function __construct(
        private HttpClientInterface $client,
        private array $config
    ) {
        $this->interpreter = new PresenceInterpreter($config);
    }

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
        $data = $response->toArray(false);
        return $this->applyInterpretation($data);
    }

    public function listConnectionsForUser(string $userId): array
    {
        $http = $this->config['http'];
        $path = str_replace('{user_id}', $userId, $http['by_user_path']);
        $response = $this->client->request('GET', rtrim($http['base_url'], '/').$path, [
            'timeout' => $http['timeout_seconds'],
        ]);
        $data = $response->toArray(false);
        return $this->applyInterpretation($data);
    }

    private function applyInterpretation(array $data): array
    {
        if (!isset($data['connections']) || !is_array($data['connections'])) {
            return $data;
        }
        $data['connections'] = $this->interpreter->filterConnections($data['connections']);
        return $data;
    }
}
