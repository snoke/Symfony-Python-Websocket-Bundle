from fastapi import FastAPI, WebSocket, Request

from . import services

app = FastAPI()


@app.on_event("startup")
async def startup_tasks():
    await services.startup_tasks()


@app.on_event("shutdown")
async def shutdown_tasks():
    await services.shutdown_tasks()


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await services.ws_endpoint(websocket)


@app.post("/internal/publish")
async def publish(payload: dict, request: Request):
    return await services.publish(payload, request)


@app.post("/internal/replay/rabbitmq")
async def replay_rabbitmq(payload: dict, request: Request):
    return await services.replay_rabbitmq(payload, request)


@app.get("/metrics")
async def metrics_endpoint():
    return await services.metrics_endpoint()


@app.get("/health")
async def health():
    return await services.health()


@app.get("/ready")
async def ready():
    return await services.ready()


@app.get("/internal/connections")
async def list_connections(subject: str | None = None, user_id: str | None = None):
    return await services.list_connections(subject=subject, user_id=user_id)


@app.get("/internal/users/{user_id}/connections")
async def user_connections(user_id: str):
    return await services.user_connections(user_id)
