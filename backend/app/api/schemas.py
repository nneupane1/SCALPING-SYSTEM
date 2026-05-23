"""Serialization helpers for API payloads."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any


def to_api_payload(value: Any) -> Any:
    """Convert domain objects into JSON-compatible primitives."""

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: to_api_payload(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_api_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_api_payload(item) for item in value]
    return value

