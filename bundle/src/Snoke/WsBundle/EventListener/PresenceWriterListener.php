<?php

namespace Snoke\WsBundle\EventListener;

use Snoke\WsBundle\Contract\PresenceWriterInterface;
use Snoke\WsBundle\Event\WebsocketConnectionClosedEvent;
use Snoke\WsBundle\Event\WebsocketConnectionEstablishedEvent;
use Snoke\WsBundle\Event\WebsocketMessageReceivedEvent;
use Symfony\Component\EventDispatcher\Attribute\AsEventListener;

class PresenceWriterListener
{
    private bool $refreshOnMessage;

    public function __construct(
        private PresenceWriterInterface $writer,
        array $config
    ) {
        $writerConfig = $config['writer'] ?? [];
        $this->refreshOnMessage = (bool) ($writerConfig['refresh_on_message'] ?? true);
    }

    #[AsEventListener(event: WebsocketConnectionEstablishedEvent::class)]
    public function onConnected(WebsocketConnectionEstablishedEvent $event): void
    {
        $this->writer->upsertConnection(
            $event->getConnectionId(),
            $event->getUserId(),
            $event->getSubjects(),
            $event->getConnectedAt()
        );
    }

    #[AsEventListener(event: WebsocketConnectionClosedEvent::class)]
    public function onClosed(WebsocketConnectionClosedEvent $event): void
    {
        $this->writer->removeConnection(
            $event->getConnectionId(),
            $event->getUserId(),
            $event->getSubjects()
        );
    }

    #[AsEventListener(event: WebsocketMessageReceivedEvent::class)]
    public function onMessage(WebsocketMessageReceivedEvent $event): void
    {
        if (!$this->refreshOnMessage) {
            return;
        }
        $this->writer->touchConnection(
            $event->getConnectionId(),
            $event->getUserId(),
            $event->getSubjects()
        );
    }
}
