"""Binance private user-data stream handling."""

from __future__ import annotations

import hashlib
import hmac
import json
import ssl
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

try:
    import websocket
except ImportError:  # pragma: no cover - exercised when optional live dependency is missing.
    websocket = None

from backend.app.config.models import ConfigBundle
from backend.app.core.models import Side

from .models import BalanceUpdate, ExecutionReportEvent, ExecutionType, OrderStatus, OrderType
from .order_manager import OrderManager


@dataclass
class BinanceAccountState:
    """Latest balances and user-stream health state."""

    balances: dict[str, BalanceUpdate] = field(default_factory=dict)
    last_event_time: datetime | None = None
    subscription_id: int | None = None


class BinanceUserDataStreamClient:
    """Maintain a private Binance user-data websocket subscription."""

    def __init__(
        self,
        *,
        config: ConfigBundle,
        api_key: str,
        api_secret: str,
        order_manager: OrderManager,
        on_event=None,
    ) -> None:
        self.config = config
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")
        self.order_manager = order_manager
        self.on_event = on_event
        self.account_state = BinanceAccountState()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws_app: websocket.WebSocketApp | None = None

    def start(self) -> None:
        if websocket is None:
            raise RuntimeError(
                "websocket-client is required for Binance user-data streaming. "
                "Install it with `pip install websocket-client`."
            )
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_forever, name="binance-user-stream", daemon=True)
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

    def _run_forever(self) -> None:
        reconnect_delay = self.config.system.binance.user_stream_reconnect_seconds
        while not self._stop_event.is_set():
            self._ws_app = websocket.WebSocketApp(
                self.config.system.binance.websocket_api_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            try:
                self._ws_app.run_forever(sslopt=_build_ssl_options(self.config))
            except Exception as exc:
                self._emit("user_stream_error", {"message": str(exc)})
            if self._stop_event.is_set():
                break
            time.sleep(reconnect_delay)

    def _on_open(self, ws_app: websocket.WebSocketApp) -> None:
        params = {
            "apiKey": self.api_key,
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "recvWindow": int(self.config.system.binance.user_stream_recv_window),
        }
        params["signature"] = _sign_websocket_params(params=params, api_secret=self.api_secret)
        payload = {
            "id": str(uuid.uuid4()),
            "method": "userDataStream.subscribe.signature",
            "params": params,
        }
        ws_app.send(json.dumps(payload))

    def _on_message(self, _ws_app: websocket.WebSocketApp, raw_message: str) -> None:
        message = json.loads(raw_message)
        if "result" in message and isinstance(message.get("result"), dict) and "subscriptionId" in message["result"]:
            self.account_state.subscription_id = int(message["result"]["subscriptionId"])
            self._emit("user_stream_subscribed", {"subscription_id": self.account_state.subscription_id})
            return
        event_payload = message.get("event")
        if not isinstance(event_payload, dict):
            return
        event_type = str(event_payload.get("e", ""))
        event_time = _from_millis(event_payload.get("E"))
        if event_time is not None:
            self.account_state.last_event_time = event_time
        if event_type == "executionReport":
            event = _parse_execution_report(event_payload)
            self.order_manager.reconcile_execution_report(event)
            self._emit("execution_report", event)
            return
        if event_type == "outboundAccountPosition":
            updates = _parse_outbound_account_position(event_payload)
            for update in updates:
                self.account_state.balances[update.asset] = update
            self._emit("account_position", updates)
            return
        if event_type == "balanceUpdate":
            update = _parse_balance_update(event_payload)
            self.account_state.balances[update.asset] = update
            self._emit("balance_update", update)
            return
        self._emit("user_stream_event", event_payload)

    def _on_error(self, _ws_app: websocket.WebSocketApp, error: object) -> None:
        self._emit("user_stream_error", {"message": str(error)})

    def _on_close(self, _ws_app: websocket.WebSocketApp, status_code: int, message: str) -> None:
        self._emit("user_stream_closed", {"status_code": status_code, "message": message})

    def _emit(self, event_type: str, payload: object) -> None:
        if callable(self.on_event):
            self.on_event(event_type, payload)


def _build_ssl_options(config: ConfigBundle) -> dict[str, object]:
    env_verify = (config.system.binance.ssl_verify and True)
    ssl_verify_override = (str(__import__("os").getenv("BINANCE_SSL_VERIFY", "")).strip().lower())
    if ssl_verify_override in {"false", "0", "no", "off"}:
        env_verify = False
    if env_verify:
        return {}
    return {"cert_reqs": ssl.CERT_NONE}


def _sign_websocket_params(*, params: dict[str, object], api_secret: bytes) -> str:
    signature_payload = "&".join(
        f"{key}={params[key]}"
        for key in sorted(params)
        if key != "signature"
    )
    return hmac.new(api_secret, signature_payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _parse_execution_report(payload: dict[str, object]) -> ExecutionReportEvent:
    return ExecutionReportEvent(
        client_order_id=str(payload["c"]),
        exchange_order_id=int(payload["i"]),
        symbol=str(payload["s"]),
        side=Side.LONG if str(payload["S"]).upper() == "BUY" else Side.SHORT,
        order_type=OrderType(str(payload["o"]).upper()),
        execution_type=ExecutionType(str(payload["x"]).upper()),
        status=OrderStatus(str(payload["X"]).upper()),
        last_executed_quantity=float(payload["l"]),
        cumulative_filled_quantity=float(payload["z"]),
        last_executed_price=float(payload["L"]),
        cumulative_quote_quantity=float(payload["Z"]),
        transaction_time=_from_millis(payload["T"]) or datetime.now(timezone.utc),
        rejection_reason=None if str(payload.get("r", "NONE")).upper() == "NONE" else str(payload.get("r")),
    )


def _parse_outbound_account_position(payload: dict[str, object]) -> tuple[BalanceUpdate, ...]:
    updated_at = _from_millis(payload.get("u")) or datetime.now(timezone.utc)
    updates: list[BalanceUpdate] = []
    for item in payload.get("B", []):
        if not isinstance(item, dict):
            continue
        updates.append(
            BalanceUpdate(
                asset=str(item["a"]).upper(),
                free=float(item["f"]),
                locked=float(item["l"]),
                updated_at=updated_at,
            )
        )
    return tuple(updates)


def _parse_balance_update(payload: dict[str, object]) -> BalanceUpdate:
    updated_at = _from_millis(payload.get("T")) or datetime.now(timezone.utc)
    return BalanceUpdate(
        asset=str(payload["a"]).upper(),
        free=float(payload["d"]),
        locked=0.0,
        updated_at=updated_at,
    )


def _from_millis(value: object) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
