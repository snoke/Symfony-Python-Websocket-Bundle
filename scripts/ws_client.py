import asyncio
import json
import os
import time
import jwt
import websockets

WS_URL = os.getenv("WS_URL", "ws://localhost:8180/ws")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
JWT_ALG = os.getenv("JWT_ALG", "RS256")
JWT_USER_ID = os.getenv("JWT_USER_ID", "42")
JWT_PRIVATE_KEY_FILE = os.getenv("JWT_PRIVATE_KEY_FILE", "")
WS_SEND_MESSAGE = os.getenv("WS_SEND_MESSAGE", "1") == "1"
WS_MESSAGE_JSON = os.getenv("WS_MESSAGE_JSON", "{\"type\":\"chat\",\"payload\":\"hello world\"}")


def make_token() -> str:
    payload = {
        "user_id": JWT_USER_ID,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    if JWT_ALG.upper().startswith("RS"):
        if not JWT_PRIVATE_KEY_FILE:
            raise RuntimeError("JWT_PRIVATE_KEY_FILE is required for RS256")
        with open(JWT_PRIVATE_KEY_FILE, "r", encoding="utf-8") as f:
            private_key = f.read()
        return jwt.encode(payload, private_key, algorithm=JWT_ALG)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


async def main() -> None:
    token = make_token()
    headers = {"Authorization": f"Bearer {token}"}
    async with websockets.connect(WS_URL, extra_headers=headers) as ws:
        await ws.send(json.dumps({"type": "ping"}))
        if WS_SEND_MESSAGE:
            await ws.send(WS_MESSAGE_JSON)
        while True:
            msg = await ws.recv()
            print("received:", msg)


if __name__ == "__main__":
    asyncio.run(main())
