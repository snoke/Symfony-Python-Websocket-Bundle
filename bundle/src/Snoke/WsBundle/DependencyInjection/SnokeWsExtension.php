<?php

namespace Snoke\WsBundle\DependencyInjection;

use Symfony\Component\DependencyInjection\ContainerBuilder;
use Symfony\Component\DependencyInjection\Extension\Extension;
use Symfony\Component\DependencyInjection\Reference;

class SnokeWsExtension extends Extension
{
    public function load(array $configs, ContainerBuilder $container): void
    {
        $configuration = new Configuration();
        $config = $this->processConfiguration($configuration, $configs);

        $mode = $config['mode'] ?? 'terminator';

        $transportType = $config['transport']['type'] ?? null;
        if (!$transportType) {
            $transportType = $mode === 'core' ? 'redis_stream' : 'http';
        }
        $config['transport']['type'] = $transportType;

        $presenceType = $config['presence']['type'] ?? null;
        if (!$presenceType) {
            $presenceType = $mode === 'core' ? 'redis' : 'http';
        }
        $config['presence']['type'] = $presenceType;

        $eventsType = $config['events']['type'] ?? null;
        if (!$eventsType) {
            $eventsType = $mode === 'core' ? 'redis_stream' : 'webhook';
        }
        $config['events']['type'] = $eventsType;

        $container->setParameter('snoke_ws.mode', $mode);
        $container->setParameter('snoke_ws.transport', $config['transport']);
        $container->setParameter('snoke_ws.presence', $config['presence']);
        $container->setParameter('snoke_ws.events', $config['events']);
        $container->setParameter('snoke_ws.subjects', $config['subjects']);

        $container->register('snoke_ws.http_publisher', 'Snoke\\WsBundle\\Service\\HttpPublisher')
            ->addArgument(new Reference('http_client'))
            ->addArgument('%snoke_ws.transport%');
        $container->register('snoke_ws.redis_stream_publisher', 'Snoke\\WsBundle\\Service\\RedisStreamPublisher')
            ->addArgument('%snoke_ws.transport%');
        $container->register('snoke_ws.rabbitmq_publisher', 'Snoke\\WsBundle\\Service\\RabbitMqPublisher')
            ->addArgument('%snoke_ws.transport%');

        $container->register('snoke_ws.dynamic_publisher', 'Snoke\\WsBundle\\Service\\DynamicPublisher')
            ->addArgument(new Reference('snoke_ws.http_publisher'))
            ->addArgument(new Reference('snoke_ws.redis_stream_publisher'))
            ->addArgument(new Reference('snoke_ws.rabbitmq_publisher'))
            ->addArgument('%snoke_ws.transport%');

        if ($presenceType === 'http') {
            $container->register('snoke_ws.http_presence', 'Snoke\\WsBundle\\Service\\HttpPresenceProvider')
                ->addArgument(new Reference('http_client'))
                ->addArgument('%snoke_ws.presence%');
            $presenceService = 'snoke_ws.http_presence';
        } else {
            $container->register('snoke_ws.redis_presence', 'Snoke\\WsBundle\\Service\\RedisPresenceProvider')
                ->addArgument('%snoke_ws.presence%');
            $presenceService = 'snoke_ws.redis_presence';
        }

        $container->register('snoke_ws.subject_key_resolver', 'Snoke\\WsBundle\\Service\\SimpleSubjectKeyResolver')
            ->addArgument('%snoke_ws.subjects%');

        $container->register('snoke_ws.publisher', 'Snoke\\WsBundle\\Service\\WebsocketPublisher')
            ->addArgument(new Reference('snoke_ws.dynamic_publisher'))
            ->addArgument(new Reference('snoke_ws.subject_key_resolver'));
        $container->setAlias('Snoke\\WsBundle\\Service\\WebsocketPublisher', 'snoke_ws.publisher');

        $container->setAlias('Snoke\\WsBundle\\Contract\\PresenceProviderInterface', $presenceService);

        $container->register('Snoke\\WsBundle\\Controller\\WebhookController', 'Snoke\\WsBundle\\Controller\\WebhookController')
            ->addArgument(new Reference('event_dispatcher'))
            ->addArgument('%snoke_ws.events%')
            ->addTag('controller.service_arguments');
        $container->setAlias('snoke_ws.webhook_controller', 'Snoke\\WsBundle\\Controller\\WebhookController');
    }
}
