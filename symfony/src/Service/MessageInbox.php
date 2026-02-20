<?php

namespace App\Service;

class MessageInbox
{
    private ?array $lastMessage = null;

    public function setLastMessage(array $payload): void
    {
        $this->lastMessage = $payload;
    }

    public function getLastMessage(): ?array
    {
        return $this->lastMessage;
    }
}
