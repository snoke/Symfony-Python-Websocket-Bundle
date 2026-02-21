import os
from typing import Any, Dict

import jwt
from fastapi import HTTPException
from jwt import PyJWKClient

from .settings import Settings


class JwtAuthenticator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def verify(self, token: str) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {}
        if self._settings.JWT_ISSUER:
            kwargs["issuer"] = self._settings.JWT_ISSUER
        if self._settings.JWT_AUDIENCE:
            kwargs["audience"] = self._settings.JWT_AUDIENCE
        if self._settings.JWT_LEEWAY:
            kwargs["leeway"] = self._settings.JWT_LEEWAY
        if self._settings.JWT_JWKS_URL:
            jwk_client = PyJWKClient(self._settings.JWT_JWKS_URL)
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            return jwt.decode(token, signing_key.key, algorithms=[self._settings.JWT_ALG], **kwargs)
        if self._settings.JWT_PUBLIC_KEY_FILE and os.path.exists(self._settings.JWT_PUBLIC_KEY_FILE):
            with open(self._settings.JWT_PUBLIC_KEY_FILE, "r", encoding="utf-8") as handle:
                public_key = handle.read()
            return jwt.decode(token, public_key, algorithms=[self._settings.JWT_ALG], **kwargs)
        if self._settings.JWT_PUBLIC_KEY:
            return jwt.decode(token, self._settings.JWT_PUBLIC_KEY, algorithms=[self._settings.JWT_ALG], **kwargs)
        raise HTTPException(status_code=500, detail="JWT config missing")
