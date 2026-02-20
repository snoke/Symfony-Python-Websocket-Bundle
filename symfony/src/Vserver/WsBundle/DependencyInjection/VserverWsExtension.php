<?php

namespace Vserver\WsBundle\DependencyInjection;

use Symfony\Component\DependencyInjection\ContainerBuilder;
use Symfony\Component\DependencyInjection\Extension\Extension;
use Symfony\Component\DependencyInjection\Reference;

class VserverWsExtension extends Extension
{
    public function load(array $configs, ContainerBuilder $container): void
    {
        $configuration = new Configuration();
        $config = $this->processConfiguration($configuration, $configs);

        $container->setParameter('vserver_ws.transport', $config['transport']);
        $container->setParameter('vserver_ws.presence', $config['presence']);
        $container->setParameter('vserver_ws.events', $config['events']);
        $container->setParameter('vserver_ws.subjects', $config['subjects']);

        $container->register('vserver_ws.http_publisher', 'Vserver\\WsBundle\\Service\\HttpPublisher')
            ->addArgument(new Reference('http_client'))
            ->addArgument('%vserver_ws.transport%');

        $container->register('vserver_ws.http_presence', 'Vserver\\WsBundle\\Service\\HttpPresenceProvider')
            ->addArgument(new Reference('http_client'))
            ->addArgument('%vserver_ws.presence%');

        $container->register('vserver_ws.subject_key_resolver', 'Vserver\\WsBundle\\Service\\SimpleSubjectKeyResolver')
            ->addArgument('%vserver_ws.subjects%');

        $container->register('vserver_ws.publisher', 'Vserver\\WsBundle\\Service\\WebsocketPublisher')
            ->addArgument(new Reference('vserver_ws.http_publisher'))
            ->addArgument(new Reference('vserver_ws.subject_key_resolver'));

        $container->register('vserver_ws.webhook_controller', 'Vserver\\WsBundle\\Controller\\WebhookController')
            ->addArgument(new Reference('event_dispatcher'))
            ->addArgument('%vserver_ws.events%')
            ->addTag('controller.service_arguments');
    }
}
