<?php

namespace Vserver\WsBundle\Contract;

interface SubjectKeyResolverInterface
{
    public function resolve(mixed $subject): string;
}
