<?php

namespace App\Controller;

use App\Service\MessageInbox;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\Routing\Annotation\Route;

class WsDemoController
{
    public function __construct(
        private MessageInbox $inbox
    ) {}

    #[Route('/api/ws/last-message', name: 'ws_last_message', methods: ['GET'])]
    public function lastMessage(): JsonResponse
    {
        $last = $this->inbox->getLastMessage();
        if ($last === null) {
            return new JsonResponse(['ok' => false, 'message' => 'no message yet'], 404);
        }
        return new JsonResponse(['ok' => true, 'data' => $last]);
    }
}
