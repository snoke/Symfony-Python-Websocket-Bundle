<?php

namespace App\Controller;

use App\Service\MessageInbox;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Annotation\Route;

class WsDemoController
{
    public function __construct(
        private MessageInbox $inbox
    ) {}

    #[Route('/api/ws/last-message', name: 'ws_last_message', methods: ['GET'])]
    public function lastMessage(Request $request): JsonResponse
    {
        $expected = $_ENV['DEMO_API_KEY'] ?? '';
        if ($expected !== '') {
            $provided = (string) $request->headers->get('X-Demo-Key', '');
            if (!hash_equals($expected, $provided)) {
                return new JsonResponse(['ok' => false, 'message' => 'unauthorized'], 401);
            }
        }
        $last = $this->inbox->getLastMessage();
        if ($last === null) {
            return new JsonResponse(['ok' => false, 'message' => 'no message yet'], 404);
        }
        return new JsonResponse(['ok' => true, 'data' => $last]);
    }
}
