<?php

namespace Snoke\WsBundle\Contract;

interface UserResolverInterface
{
    public function resolve(string $userId): mixed;
}
