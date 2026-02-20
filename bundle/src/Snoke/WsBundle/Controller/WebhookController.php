<?php

namespace Snoke\WsBundle\Controller;

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Annotation\Route;
use Symfony\Contracts\EventDispatcher\EventDispatcherInterface;
use Snoke\WsBundle\Event\WebsocketConnectionEstablishedEvent;
use Snoke\WsBundle\Event\WebsocketConnectionClosedEvent;
use Snoke\WsBundle\Event\WebsocketMessageReceivedEvent;

class WebhookController
{
    public function __construct(
        private EventDispatcherInterface $dispatcher,
        private array $config
    ) {}

    #[Route('/internal/ws/events', name: 'snoke_ws_events', methods: ['POST'])]
    public function handle(Request $request): JsonResponse
    {
        $events = $this->config['events'];
        if (($events['type'] ?? 'none') !== 'webhook' || !($events['webhook']['enabled'] ?? false)) {
            return new JsonResponse(['ok' => false], 404);
        }

        $data = json_decode($request->getContent(), true) ?? [];
        $type = $data['type'] ?? '';
        $connectionId = (string) ($data['connection_id'] ?? '');
        $userId = (string) ($data['user_id'] ?? '');
        $subjects = $data['subjects'] ?? [];
        $connectedAt = (int) ($data['connected_at'] ?? 0);
        $message = $data['message'] ?? null;
        $raw = (string) ($data['raw'] ?? '');

        if ($type === 'connected') {
            $this->dispatcher->dispatch(new WebsocketConnectionEstablishedEvent(
                $connectionId,
                $userId,
                $subjects,
                $connectedAt
            ));
        }

        if ($type === 'disconnected') {
            $this->dispatcher->dispatch(new WebsocketConnectionClosedEvent(
                $connectionId,
                $userId,
                $subjects,
                $connectedAt
            ));
        }
        if ($type === 'message_received') {
            $this->dispatcher->dispatch(new WebsocketMessageReceivedEvent(
                $connectionId,
                $userId,
                $subjects,
                $connectedAt,
                $message,
                $raw
            ));
        }

        return new JsonResponse(['ok' => true]);
    }
}
