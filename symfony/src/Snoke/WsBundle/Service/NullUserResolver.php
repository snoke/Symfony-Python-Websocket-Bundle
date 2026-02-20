<?php

namespace Snoke\WsBundle\Service;

use Snoke\WsBundle\Contract\UserResolverInterface;

class NullUserResolver implements UserResolverInterface
{
    public function resolve(string $userId): mixed
    {
        return null;
    }
}
