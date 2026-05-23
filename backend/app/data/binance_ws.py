"""Binance WebSocket helpers.

This module deliberately stops short of opening a real network connection in the
current pass. Its job is to formalize stream naming, payload decoding, and the
contract that a future transport implementation must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .models import Tick


@dataclass(frozen=True)
class BinanceStreamRequest:
    """A requested Binance stream."""

    symbol: str
    channel: str

    @property
    def stream_name(self) -> str:
        return f"{self.symbol.lower()}@{self.channel}"


class BinanceWebSocketClient:
    """Helpers for stream naming and payload decoding."""

    BASE_URL = "wss://stream.binance.com:9443/stream?streams="

    def build_stream_url(self, requests: tuple[BinanceStreamRequest, ...]) -> str:
        if not requests:
            raise ValueError("At least one stream request is required.")
        joined = "/".join(request.stream_name for request in requests)
        return f"{self.BASE_URL}{joined}"

    def decode_trade_event(self, payload: Mapping[str, Any]) -> Tick:
        data = payload.get("data", payload)
        symbol = str(data["s"]).upper()
        price = float(data["p"])
        quantity = float(data["q"])
        event_time_ms = int(data["T"])
        event_time = datetime.fromtimestamp(event_time_ms / 1000, tz=timezone.utc)
        return Tick(symbol=symbol, price=price, quantity=quantity, event_time=event_time)

