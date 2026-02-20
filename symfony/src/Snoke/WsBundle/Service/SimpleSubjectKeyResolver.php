<?php

namespace Snoke\WsBundle\Service;

use Snoke\WsBundle\Contract\ConnectionSubjectInterface;
use Snoke\WsBundle\Contract\SubjectKeyResolverInterface;

class SimpleSubjectKeyResolver implements SubjectKeyResolverInterface
{
    public function __construct(private array $config) {}

    public function resolve(mixed $subject): string
    {
        if ($subject instanceof ConnectionSubjectInterface) {
            return $subject->subjectKey();
        }
        if (is_string($subject)) {
            if (str_starts_with($subject, $this->config['user_prefix'])) {
                return $subject;
            }
            return $this->config['user_prefix'].$subject;
        }
        return (string) $subject;
    }
}
