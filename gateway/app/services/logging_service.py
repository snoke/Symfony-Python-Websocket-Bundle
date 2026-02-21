import json
import logging
import sys
from typing import Any

from .settings import Settings


class LoggingService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.logger = logging.getLogger("gateway")
        self.logger.setLevel(getattr(logging, settings.LOG_LEVEL, logging.INFO))
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(self.logger.level)
            self.logger.addHandler(handler)

    def log(self, event: str, **fields: Any) -> None:
        payload = {"event": event, **fields}
        if self._settings.LOG_FORMAT == "json":
            self.logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        else:
            self.logger.info("%s %s", event, payload)
