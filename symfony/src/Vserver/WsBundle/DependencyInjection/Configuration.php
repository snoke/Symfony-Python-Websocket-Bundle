<?php

namespace Vserver\WsBundle\DependencyInjection;

use Symfony\Component\Config\Definition\Builder\TreeBuilder;
use Symfony\Component\Config\Definition\ConfigurationInterface;

class Configuration implements ConfigurationInterface
{
    public function getConfigTreeBuilder(): TreeBuilder
    {
        $treeBuilder = new TreeBuilder('vserver_ws');
        $root = $treeBuilder->getRootNode();

        $root
            ->children()
                ->arrayNode('transport')
                    ->children()
                        ->enumNode('type')->values(['http'])->defaultValue('http')->end()
                        ->arrayNode('http')
                            ->children()
                                ->scalarNode('base_url')->isRequired()->end()
                                ->scalarNode('publish_path')->defaultValue('/internal/publish')->end()
                                ->integerNode('timeout_seconds')->defaultValue(5)->end()
                                ->arrayNode('auth')
                                    ->children()
                                        ->enumNode('type')->values(['api_key', 'none'])->defaultValue('api_key')->end()
                                        ->scalarNode('header')->defaultValue('X-Api-Key')->end()
                                        ->scalarNode('value')->defaultValue('')->end()
                                    ->end()
                                ->end()
                            ->end()
                        ->end()
                    ->end()
                ->end()
                ->arrayNode('presence')
                    ->children()
                        ->enumNode('type')->values(['http'])->defaultValue('http')->end()
                        ->arrayNode('http')
                            ->children()
                                ->scalarNode('base_url')->isRequired()->end()
                                ->scalarNode('list_path')->defaultValue('/internal/connections')->end()
                                ->scalarNode('by_user_path')->defaultValue('/internal/users/{user_id}/connections')->end()
                                ->integerNode('timeout_seconds')->defaultValue(5)->end()
                            ->end()
                        ->end()
                    ->end()
                ->end()
                ->arrayNode('events')
                    ->children()
                        ->enumNode('type')->values(['webhook', 'none'])->defaultValue('webhook')->end()
                        ->arrayNode('webhook')
                            ->children()
                                ->scalarNode('path')->defaultValue('/internal/ws/events')->end()
                                ->booleanNode('enabled')->defaultValue(true)->end()
                            ->end()
                        ->end()
                    ->end()
                ->end()
                ->arrayNode('subjects')
                    ->children()
                        ->scalarNode('user_prefix')->defaultValue('user:')->end()
                    ->end()
                ->end()
            ->end();

        return $treeBuilder;
    }
}
