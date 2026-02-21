from .app import GatewayApp
from .settings import load_settings

_app = GatewayApp(load_settings())


async def startup_tasks():
    await _app.startup_tasks()


async def shutdown_tasks():
    await _app.shutdown_tasks()


async def ws_endpoint(websocket):
    await _app.ws_endpoint(websocket)


async def publish(payload, request):
    return await _app.publish(payload, request)


async def replay_rabbitmq(payload, request):
    return await _app.replay_rabbitmq(payload, request)


async def metrics_endpoint():
    return await _app.metrics_endpoint()


async def health():
    return await _app.health()


async def ready():
    return await _app.ready()


async def list_connections(subject=None, user_id=None):
    return await _app.list_connections(subject=subject, user_id=user_id)


async def user_connections(user_id):
    return await _app.user_connections(user_id)
