<?php

namespace Vserver\WsBundle\Service;

use Vserver\WsBundle\Contract\UserResolverInterface;

class NullUserResolver implements UserResolverInterface
{
    public function resolve(string $userId): mixed
    {
        return null;
    }
}
