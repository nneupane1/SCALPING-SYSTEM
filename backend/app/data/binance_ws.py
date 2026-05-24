"""Binance public websocket helpers and closed-kline stream client."""

from __future__ import annotations

import json
import os
import queue
import ssl
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
try:
    import websocket
except ImportError:  # pragma: no cover - exercised when optional live dependency is missing.
    websocket = None

from backend.app.config.models import ConfigBundle

from .models import Tick


@dataclass(frozen=True)
class BinanceStreamRequest:
    """A requested Binance stream."""

    symbol: str
    channel: str

    @property
    def stream_name(self) -> str:
        return f"{self.symbol.lower()}@{self.channel}"


@dataclass(frozen=True)
class ClosedKlineEvent:
    """A closed Binance kline event ready for dataframe ingestion."""

    symbol: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int

    def to_frame(self) -> pd.DataFrame:
        frame = pd.DataFrame(
            [
                {
                    "open": self.open,
                    "high": self.high,
                    "low": self.low,
                    "close": self.close,
                    "volume": self.volume,
                    "trade_count": self.trade_count,
                }
            ],
            index=[pd.Timestamp(self.open_time)],
        )
        frame.index.name = "timestamp"
        return frame


class BinanceWebSocketClient:
    """Helpers for stream naming and payload decoding."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or "wss://stream.binance.com:9443/stream?streams="

    def build_stream_url(self, requests: tuple[BinanceStreamRequest, ...]) -> str:
        if not requests:
            raise ValueError("At least one stream request is required.")
        joined = "/".join(request.stream_name for request in requests)
        return f"{self.base_url}{joined}"

    def decode_trade_event(self, payload: Mapping[str, Any]) -> Tick:
        data = payload.get("data", payload)
        symbol = str(data["s"]).upper()
        price = float(data["p"])
        quantity = float(data["q"])
        event_time_ms = int(data["T"])
        event_time = datetime.fromtimestamp(event_time_ms / 1000, tz=timezone.utc)
        return Tick(symbol=symbol, price=price, quantity=quantity, event_time=event_time)

    def decode_closed_kline_event(self, payload: Mapping[str, Any]) -> ClosedKlineEvent | None:
        data = payload.get("data", payload)
        if str(data.get("e", "")).lower() != "kline":
            return None
        kline = data.get("k")
        if not isinstance(kline, Mapping):
            return None
        if not bool(kline.get("x")):
            return None
        return ClosedKlineEvent(
            symbol=str(kline["s"]).upper() if "s" in kline else str(data["s"]).upper(),
            interval=str(kline["i"]),
            open_time=_naive_utc_from_millis(kline["t"]),
            close_time=_naive_utc_from_millis(kline["T"]),
            open=float(kline["o"]),
            high=float(kline["h"]),
            low=float(kline["l"]),
            close=float(kline["c"]),
            volume=float(kline["v"]),
            trade_count=int(kline.get("n", 0)),
        )


class BinanceMarketStreamClient:
    """Reconnect-capable client for public Binance kline streams."""

    def __init__(
        self,
        *,
        config: ConfigBundle,
        requests: tuple[BinanceStreamRequest, ...],
        on_closed_kline=None,
        on_event=None,
    ) -> None:
        self.config = config
        self.requests = requests
        self.on_closed_kline = on_closed_kline
        self.on_event = on_event
        self.decoder = BinanceWebSocketClient(base_url=config.system.binance.websocket_stream_url)
        self.url = self.decoder.build_stream_url(requests)
        self._queue: queue.Queue[ClosedKlineEvent] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws_app: websocket.WebSocketApp | None = None
        self._last_message_at: float | None = None

    def start(self) -> None:
        if websocket is None:
            raise RuntimeError(
                "websocket-client is required for Binance market streaming. "
                "Install it with `pip install websocket-client`."
            )
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_forever, name="binance-market-stream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._ws_app is not None:
            try:
                self._ws_app.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def wait_for_closed_kline(self, timeout_seconds: float) -> ClosedKlineEvent | None:
        try:
            return self._queue.get(timeout=timeout_seconds)
        except queue.Empty:
            return None

    def _run_forever(self) -> None:
        reconnect_delay = self.config.system.binance.market_stream_reconnect_seconds
        while not self._stop_event.is_set():
            self._ws_app = websocket.WebSocketApp(
                self.url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            self._last_message_at = time.time()
            try:
                self._ws_app.run_forever(sslopt=_build_ssl_options(self.config), ping_interval=20, ping_timeout=10)
            except Exception as exc:
                self._emit("market_stream_error", {"message": str(exc)})
            if self._stop_event.is_set():
                break
            time.sleep(reconnect_delay)

    def _on_open(self, _ws_app: websocket.WebSocketApp) -> None:
        self._last_message_at = time.time()
        self._emit("market_stream_opened", {"url": self.url})

    def _on_message(self, _ws_app: websocket.WebSocketApp, raw_message: str) -> None:
        self._last_message_at = time.time()
        payload = json.loads(raw_message)
        event = self.decoder.decode_closed_kline_event(payload)
        if event is None:
            return
        self._queue.put(event)
        if callable(self.on_closed_kline):
            self.on_closed_kline(event)
        self._emit(
            "closed_kline",
            {
                "symbol": event.symbol,
                "interval": event.interval,
                "close_time": event.close_time.isoformat(),
                "close": event.close,
            },
        )

    def _on_error(self, _ws_app: websocket.WebSocketApp, error: object) -> None:
        self._emit("market_stream_error", {"message": str(error)})

    def _on_close(self, _ws_app: websocket.WebSocketApp, status_code: int, message: str) -> None:
        self._emit("market_stream_closed", {"status_code": status_code, "message": message})

    def _emit(self, event_type: str, payload: object) -> None:
        if callable(self.on_event):
            self.on_event(event_type, payload)


def _build_ssl_options(config: ConfigBundle) -> dict[str, object]:
    verify_override = (os.getenv("BINANCE_SSL_VERIFY") or "").strip().lower()
    if verify_override in {"false", "0", "no", "off"}:
        return {"cert_reqs": ssl.CERT_NONE}
    if config.system.binance.ca_bundle_path:
        bundle_path = Path(config.system.binance.ca_bundle_path)
        if not bundle_path.is_absolute():
            bundle_path = Path.cwd() / bundle_path
        return {"ca_certs": str(bundle_path)}
    if config.system.binance.ssl_verify:
        return {}
    return {"cert_reqs": ssl.CERT_NONE}


def _naive_utc_from_millis(value: object) -> datetime:
    timestamp = datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    return timestamp.replace(tzinfo=None)
