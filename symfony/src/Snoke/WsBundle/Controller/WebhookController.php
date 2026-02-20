<?php

namespace Snoke\WsBundle\Controller;

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Annotation\Route;
use Symfony\Contracts\EventDispatcher\EventDispatcherInterface;
use Snoke\WsBundle\Event\WebsocketConnectionEstablishedEvent;
use Snoke\WsBundle\Event\WebsocketConnectionClosedEvent;

class WebhookController
{
    public function __construct(
        private EventDispatcherInterface $dispatcher,
        private array $config
    ) {}

    #[Route('/internal/ws/events', name: 'vserver_ws_events', methods: ['POST'])]
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

        return new JsonResponse(['ok' => true]);
    }
}
