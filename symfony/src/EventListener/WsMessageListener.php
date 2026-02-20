<?php

namespace App\EventListener;

use App\Service\MessageInbox;
use Psr\Log\LoggerInterface;
use Snoke\WsBundle\Event\WebsocketMessageReceivedEvent;
use Symfony\Component\EventDispatcher\Attribute\AsEventListener;

#[AsEventListener(event: WebsocketMessageReceivedEvent::class)]
class WsMessageListener
{
    public function __construct(
        private MessageInbox $inbox,
        private LoggerInterface $logger
    ) {}

    public function __invoke(WebsocketMessageReceivedEvent $event): void
    {
        $payload = [
            'connection_id' => $event->getConnectionId(),
            'user_id' => $event->getUserId(),
            'subjects' => $event->getSubjects(),
            'connected_at' => $event->getConnectedAt(),
            'message' => $event->getMessage(),
            'raw' => $event->getRaw(),
            'received_at' => time(),
        ];

        $this->inbox->setLastMessage($payload);
        $this->logger->info('ws.message_received', $payload);
    }
}
