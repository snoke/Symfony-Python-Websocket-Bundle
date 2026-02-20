<?php

namespace App\Controller;

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Annotation\Route;
use Snoke\WsBundle\Service\WebsocketPublisher;
use Snoke\WsBundle\Contract\PresenceProviderInterface;

class DemoController
{
    #[Route('/api/ping', name: 'api_ping', methods: ['GET'])]
    public function ping(): JsonResponse
    {
        return new JsonResponse(['ok' => true]);
    }

    #[Route('/api/push-demo/{userId}', name: 'api_push_demo', methods: ['POST'])]
    public function pushDemo(string $userId, WebsocketPublisher $publisher): JsonResponse
    {
        $publisher->send(["user:".$userId], ['hello' => 'world']);
        return new JsonResponse(['sent' => true]);
    }

    #[Route('/api/online', name: 'api_online', methods: ['GET'])]
    public function online(Request $request, PresenceProviderInterface $presence): JsonResponse
    {
        $userId = $request->query->get('user_id');
        if (is_string($userId) && $userId !== '') {
            $result = $presence->listConnectionsForUser($userId);
        } else {
            $result = $presence->listConnections();
        }
        return new JsonResponse($result);
    }
}
