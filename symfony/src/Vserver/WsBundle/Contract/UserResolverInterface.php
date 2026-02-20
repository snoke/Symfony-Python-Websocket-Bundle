<?php

namespace Vserver\WsBundle\Contract;

interface UserResolverInterface
{
    public function resolve(string $userId): mixed;
}
