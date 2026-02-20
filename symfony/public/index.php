<?php

use App\Kernel;
use Symfony\Component\HttpFoundation\Request;

require dirname(__DIR__).'/vendor/autoload.php';

$env = $_SERVER['APP_ENV'] ?? 'dev';
$debug = isset($_SERVER['APP_DEBUG']) ? (bool) $_SERVER['APP_DEBUG'] : ($env !== 'prod');
$kernel = new Kernel($env, $debug);
$request = Request::createFromGlobals();
$response = $kernel->handle($request);
$response->send();
$kernel->terminate($request, $response);
