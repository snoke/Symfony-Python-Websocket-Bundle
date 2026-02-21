import hashlib
import re
from typing import Any, Optional, Tuple

from .settings import Settings


_ORDERING_KEY_SAFE_RE = re.compile(r"[^A-Za-z0-9._:-]")


class OrderingService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _normalize_ordering_key(self, raw_key: str) -> str:
        key = (raw_key or "").strip()
        if not key:
            return ""
        raw_bytes = key.encode("utf-8")
        if self._settings.ORDERING_PARTITION_MAX_LEN > 0 and len(key) > self._settings.ORDERING_PARTITION_MAX_LEN:
            key = hashlib.sha1(raw_bytes).hexdigest()
        key = _ORDERING_KEY_SAFE_RE.sub("_", key)
        if not key:
            key = hashlib.sha1(raw_bytes).hexdigest()
        return key

    def derive_ordering_key(self, conn, data: Optional[dict]) -> str:
        if self._settings.ORDERING_STRATEGY == "none":
            return ""
        if self._settings.ORDERING_STRATEGY == "topic":
            if not data:
                return ""
            key = data.get(self._settings.ORDERING_TOPIC_FIELD)
            if key is None and isinstance(data.get("meta"), dict):
                key = data["meta"].get(self._settings.ORDERING_TOPIC_FIELD)
            if key is None:
                key = data.get("type")
            return str(key) if key else ""
        if self._settings.ORDERING_STRATEGY == "subject":
            key = None
            if data:
                if isinstance(data.get("subject"), str):
                    key = data.get("subject")
                elif isinstance(data.get("subjects"), list) and data.get("subjects"):
                    key = data.get("subjects")[0]
            if not key:
                if self._settings.ORDERING_SUBJECT_SOURCE == "subject" and getattr(conn, "subjects", None):
                    key = sorted(conn.subjects)[0]
                else:
                    key = conn.user_id
            return str(key) if key else ""
        return ""

    def apply_partition(self, stream: Optional[str], routing_key: str, ordering_key: str) -> Tuple[Optional[str], str]:
        if self._settings.ORDERING_PARTITION_MODE != "suffix" or not ordering_key:
            return stream, routing_key
        safe_key = self._normalize_ordering_key(ordering_key)
        if not safe_key:
            return stream, routing_key
        if stream:
            stream = f"{stream}.{safe_key}"
        routing_key = f"{routing_key}.{safe_key}"
        return stream, routing_key
