<?php

namespace Snoke\WsBundle\Contract;

interface SubjectKeyResolverInterface
{
    public function resolve(mixed $subject): string;
}
