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

        $container->setParameter('vserver_ws.transport', $config['transport']);
        $container->setParameter('vserver_ws.presence', $config['presence']);
        $container->setParameter('vserver_ws.events', $config['events']);
        $container->setParameter('vserver_ws.subjects', $config['subjects']);

        $transportType = $config['transport']['type'] ?? 'http';
        if ($transportType === 'http') {
            $container->register('vserver_ws.http_publisher', 'Vserver\\WsBundle\\Service\\HttpPublisher')
                ->addArgument(new Reference('http_client'))
                ->addArgument('%vserver_ws.transport%');
            $publisherService = 'vserver_ws.http_publisher';
        } elseif ($transportType === 'redis_stream') {
            $container->register('vserver_ws.redis_stream_publisher', 'Vserver\\WsBundle\\Service\\RedisStreamPublisher')
                ->addArgument('%vserver_ws.transport%');
            $publisherService = 'vserver_ws.redis_stream_publisher';
        } else {
            $container->register('vserver_ws.rabbitmq_publisher', 'Vserver\\WsBundle\\Service\\RabbitMqPublisher')
                ->addArgument('%vserver_ws.transport%');
            $publisherService = 'vserver_ws.rabbitmq_publisher';
        }

        $presenceType = $config['presence']['type'] ?? 'http';
        if ($presenceType === 'http') {
            $container->register('vserver_ws.http_presence', 'Vserver\\WsBundle\\Service\\HttpPresenceProvider')
                ->addArgument(new Reference('http_client'))
                ->addArgument('%vserver_ws.presence%');
            $presenceService = 'vserver_ws.http_presence';
        } else {
            $container->register('vserver_ws.redis_presence', 'Vserver\\WsBundle\\Service\\RedisPresenceProvider')
                ->addArgument('%vserver_ws.presence%');
            $presenceService = 'vserver_ws.redis_presence';
        }

        $container->register('vserver_ws.subject_key_resolver', 'Vserver\\WsBundle\\Service\\SimpleSubjectKeyResolver')
            ->addArgument('%vserver_ws.subjects%');

        $container->register('vserver_ws.publisher', 'Vserver\\WsBundle\\Service\\WebsocketPublisher')
            ->addArgument(new Reference($publisherService))
            ->addArgument(new Reference('vserver_ws.subject_key_resolver'));

        $container->setAlias('Vserver\\WsBundle\\Contract\\PresenceProviderInterface', $presenceService);

        $container->register('vserver_ws.webhook_controller', 'Vserver\\WsBundle\\Controller\\WebhookController')
            ->addArgument(new Reference('event_dispatcher'))
            ->addArgument('%vserver_ws.events%')
            ->addTag('controller.service_arguments');
    }
}
