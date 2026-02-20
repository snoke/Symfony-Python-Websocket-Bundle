<?php

namespace App\Controller;

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\Routing\Annotation\Route;
use Vserver\WsBundle\Service\WebsocketPublisher;

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
}
