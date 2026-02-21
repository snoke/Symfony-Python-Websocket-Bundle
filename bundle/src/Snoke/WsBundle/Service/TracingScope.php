<?php

namespace Snoke\WsBundle\Service;

use OpenTelemetry\API\Trace\SpanInterface;
use OpenTelemetry\Context\ScopeInterface;

class TracingScope
{
    public function __construct(
        private SpanInterface $span,
        private ?ScopeInterface $scope
    ) {}

    public function end(): void
    {
        if ($this->scope) {
            $this->scope->detach();
        }
        $this->span->end();
    }
}
