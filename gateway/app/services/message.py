from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class MessageFlags:
    encrypted: bool = False
    qos: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if self.encrypted:
            data["encrypted"] = True
        if self.qos:
            data["qos"] = self.qos
        return data


@dataclass
class InternalMessage:
    schema_version: int
    internal_id: str
    timestamp_ms: int
    user_id: str
    channel_id: str
    flags: MessageFlags
    payload: Any

    def to_client_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.internal_id,
            "ts": self.timestamp_ms,
            "channel_id": self.channel_id,
            "payload": self.payload,
        }
        if self.flags.encrypted:
            payload["encrypted"] = True
        if self.flags.qos:
            payload["qos"] = self.flags.qos
        return payload


def extract_channel_id(data: Dict[str, Any], fallback: str) -> str:
    for key in ("channel_id", "channel", "topic"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def extract_payload(data: Dict[str, Any]) -> Any:
    if "payload" in data:
        return data.get("payload")
    return data


def extract_flags(data: Dict[str, Any]) -> MessageFlags:
    flags = MessageFlags()
    if isinstance(data.get("encrypted"), bool):
        flags.encrypted = bool(data.get("encrypted"))
    nested = data.get("flags")
    if isinstance(nested, dict) and isinstance(nested.get("encrypted"), bool):
        flags.encrypted = bool(nested.get("encrypted"))
    qos = data.get("qos")
    if isinstance(qos, str) and qos:
        flags.qos = qos
    if isinstance(nested, dict):
        qos = nested.get("qos")
        if isinstance(qos, str) and qos:
            flags.qos = qos
    return flags


def internal_from_dict(data: Dict[str, Any]) -> Optional[InternalMessage]:
    internal_id = data.get("internal_id")
    timestamp_ms = data.get("timestamp_ms")
    user_id = data.get("user_id")
    channel_id = data.get("channel_id")
    payload = data.get("payload")
    if not internal_id or not user_id or not channel_id:
        return None
    if not isinstance(timestamp_ms, int):
        return None
    flags_data = data.get("flags")
    flags = MessageFlags()
    if isinstance(flags_data, dict):
        if isinstance(flags_data.get("encrypted"), bool):
            flags.encrypted = bool(flags_data.get("encrypted"))
        qos = flags_data.get("qos")
        if isinstance(qos, str) and qos:
            flags.qos = qos
    return InternalMessage(
        schema_version=int(data.get("schema_version") or 1),
        internal_id=str(internal_id),
        timestamp_ms=timestamp_ms,
        user_id=str(user_id),
        channel_id=str(channel_id),
        flags=flags,
        payload=payload,
    )
