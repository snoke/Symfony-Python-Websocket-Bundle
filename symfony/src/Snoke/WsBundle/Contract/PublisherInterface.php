<?php

namespace Snoke\WsBundle\Contract;

interface PublisherInterface
{
    public function publish(array $subjectKeys, mixed $payload): void;
}
