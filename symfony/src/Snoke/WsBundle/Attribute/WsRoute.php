<?php

namespace Snoke\WsBundle\Attribute;

use Attribute;

#[Attribute(Attribute::TARGET_METHOD)]
class WsRoute
{
    public function __construct(
        public string $path,
        public array $options = []
    ) {}
}
