<?php

namespace Snoke\WsBundle\Controller;

use Snoke\WsBundle\Event\WebsocketConnectionClosedEvent;
use Snoke\WsBundle\Event\WebsocketConnectionEstablishedEvent;
use Snoke\WsBundle\Event\WebsocketMessageReceivedEvent;
use Snoke\WsBundle\Service\TracingService;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Annotation\Route;
use Symfony\Contracts\EventDispatcher\EventDispatcherInterface;
use OpenTelemetry\API\Trace\SpanKind;

class WebhookController
{
    public function __construct(
        private EventDispatcherInterface $dispatcher,
        private array $config,
        private TracingService $tracing
    ) {}

    #[Route('/internal/ws/events', name: 'snoke_ws_events', methods: ['POST'])]
    public function handle(Request $request): JsonResponse
    {
        $events = $this->config ?? [];
        if (($events['type'] ?? 'none') !== 'webhook' || !($events['webhook']['enabled'] ?? false)) {
            return new JsonResponse(['ok' => false, 'message' => 'webhook disabled'], 404);
        }

        $secret = $_ENV['SYMFONY_WEBHOOK_SECRET'] ?? '';
        if ($secret !== '') {
            $signature = (string) $request->headers->get('X-Webhook-Signature', '');
            if ($signature === '' || !str_starts_with($signature, 'sha256=')) {
                return new JsonResponse(['ok' => false, 'message' => 'missing signature'], 401);
            }
            $expected = 'sha256=' . hash_hmac('sha256', $request->getContent(), $secret);
            if (!hash_equals($expected, $signature)) {
                return new JsonResponse(['ok' => false, 'message' => 'invalid signature'], 401);
            }
        }

        $data = json_decode($request->getContent(), true) ?? [];
        $type = (string) ($data['type'] ?? '');
        $connectionId = (string) ($data['connection_id'] ?? '');
        $userId = (string) ($data['user_id'] ?? '');
        $subjects = $data['subjects'] ?? [];
        $connectedAt = (int) ($data['connected_at'] ?? 0);
        $message = $data['message'] ?? null;
        $raw = (string) ($data['raw'] ?? '');

        $traceparent = (string) $request->headers->get('traceparent', '');
        $traceparentField = $this->tracing->getTraceparentField();
        if ($traceparent === '' && isset($data[$traceparentField])) {
            $traceparent = (string) $data[$traceparentField];
        }

        $scope = $this->tracing->startSpan('ws.webhook', SpanKind::KIND_SERVER, [
            'ws.event_type' => $type,
            'ws.connection_id' => $connectionId,
            'ws.user_id' => $userId,
        ], $traceparent);

        try {
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
        } finally {
            if ($scope) {
                $scope->end();
            }
        }

        return new JsonResponse(['ok' => true]);
    }
}
