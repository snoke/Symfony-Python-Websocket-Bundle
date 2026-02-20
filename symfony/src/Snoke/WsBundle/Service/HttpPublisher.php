<?php

namespace Snoke\WsBundle\Service;

use Symfony\Contracts\HttpClient\HttpClientInterface;
use Snoke\WsBundle\Contract\PublisherInterface;

class HttpPublisher implements PublisherInterface
{
    public function __construct(
        private HttpClientInterface $client,
        private array $config
    ) {}

    public function publish(array $subjectKeys, mixed $payload): void
    {
        $http = $this->config['http'];
        $auth = $http['auth'] ?? ['type' => 'none'];

        $body = [
            'subjects' => $subjectKeys,
            'payload' => $payload,
        ];

        if (($auth['type'] ?? 'none') === 'api_key') {
            $body['api_key'] = $auth['value'] ?? '';
        }

        $this->client->request('POST', rtrim($http['base_url'], '/').$http['publish_path'], [
            'json' => $body,
            'timeout' => $http['timeout_seconds'],
        ]);
    }
}
