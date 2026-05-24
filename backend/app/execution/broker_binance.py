"""Authenticated Binance spot broker adapter."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning

from backend.app.config import load_env_file
from backend.app.config.models import ConfigBundle
from backend.app.core.models import Side

from .broker_base import Broker
from .exchange_metadata import ExchangeMetadataService, NormalizedOrder
from .models import (
    BrokerOrderState,
    FillReport,
    OrderFill,
    OrderRequest,
    OrderStatus,
    OrderType,
)
from .order_manager import OrderManager


class BinanceBroker(Broker):
    """Authenticated Binance spot broker with retry and recovery logic.

    The adapter is intentionally conservative:
    - it refuses to open short spot positions
    - it recovers uncertain submissions by querying the exchange using the
      client order id before retrying
    - it lets the user-data stream become the source of truth when available
    """

    def __init__(
        self,
        *,
        config: ConfigBundle,
        order_manager: OrderManager,
        session: requests.Session | None = None,
        on_event=None,
    ) -> None:
        load_env_file()
        self.config = config
        self.order_manager = order_manager
        self.on_event = on_event
        self.session = session or requests.Session()
        self.binance = config.system.binance
        self.api_key = (os.getenv("BINANCE_API_KEY") or "").strip()
        self.api_secret = (os.getenv("BINANCE_API_SECRET") or "").strip()
        if not self.api_key or not self.api_secret:
            raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET are required for live Binance routing.")
        self._api_secret_bytes = self.api_secret.encode("utf-8")
        self._warnings_configured = False
        self.order_url = urljoin(self.binance.base_url.rstrip("/") + "/", self.binance.order_path.lstrip("/"))
        self.open_orders_url = urljoin(
            self.binance.base_url.rstrip("/") + "/",
            self.binance.open_orders_path.lstrip("/"),
        )
        self.account_url = urljoin(self.binance.base_url.rstrip("/") + "/", self.binance.account_path.lstrip("/"))
        self.exchange_metadata = ExchangeMetadataService(config=config, session=self.session)

    def is_live(self) -> bool:
        return True

    def supports_resting_orders(self) -> bool:
        return True

    def submit_order(self, request: OrderRequest) -> FillReport:
        normalized = self.exchange_metadata.normalize_order(request)
        effective_request = replace(
            request,
            quantity=float(normalized.quantity),
            price=None if normalized.price is None else float(normalized.price),
            stop_price=None if normalized.stop_price is None else float(normalized.stop_price),
        )
        params = self._build_order_params(normalized)
        max_attempts = max(1, self.binance.order_submit_retry_attempts)
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                payload = self._signed_request("POST", self.order_url, params=params)
                fill = self._parse_fill_report(request=effective_request, payload=payload, simulated=False)
                self.order_manager.register_submission_result(effective_request, fill)
                self._emit(
                    "order_submitted",
                    {
                        "client_order_id": effective_request.order_id,
                        "exchange_order_id": fill.exchange_order_id,
                        "symbol": effective_request.symbol,
                        "reason": effective_request.reason,
                        "status": fill.status.value,
                        "normalized_quantity": str(normalized.quantity),
                        "estimated_notional": str(normalized.estimated_notional),
                    },
                )
                return self._settle_entry_fill(request=effective_request, fill=fill)
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                last_error = exc
                recovered = self._recover_submission(request=effective_request)
                if recovered is not None:
                    return recovered
                if attempt >= max_attempts:
                    break
                delay = self.binance.order_submit_retry_delay_seconds * attempt
                self._emit(
                    "order_retry",
                    {
                        "client_order_id": effective_request.order_id,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "delay": delay,
                        "reason": str(exc),
                    },
                )
                time.sleep(delay)

        raise RuntimeError(
            f"Binance order submission failed after {max_attempts} attempts for {effective_request.order_id}: {last_error}"
        )

    def cancel_order(
        self,
        *,
        symbol: str,
        client_order_id: str,
        exchange_order_id: int | None = None,
    ) -> BrokerOrderState | None:
        params: dict[str, object] = {"symbol": symbol.upper()}
        if exchange_order_id is not None:
            params["orderId"] = exchange_order_id
        else:
            params["origClientOrderId"] = client_order_id

        try:
            payload = self._signed_request("DELETE", self.order_url, params=params)
        except (requests.RequestException, RuntimeError):
            state = self.fetch_order(
                symbol=symbol,
                client_order_id=client_order_id,
                exchange_order_id=exchange_order_id,
            )
            if state is not None and state.status.is_terminal:
                return state
            raise

        occurred_at = self._timestamp_from_millis(payload.get("transactTime")) or datetime.now(timezone.utc)
        exchange_id = int(payload["orderId"]) if payload.get("orderId") is not None else exchange_order_id
        self.order_manager.register_cancellation(
            client_order_id,
            exchange_order_id=exchange_id,
            occurred_at=occurred_at,
        )
        return self.fetch_order(symbol=symbol, client_order_id=client_order_id, exchange_order_id=exchange_id)

    def fetch_order(
        self,
        *,
        symbol: str,
        client_order_id: str | None = None,
        exchange_order_id: int | None = None,
    ) -> BrokerOrderState | None:
        params: dict[str, object] = {"symbol": symbol.upper()}
        if exchange_order_id is not None:
            params["orderId"] = exchange_order_id
        elif client_order_id is not None:
            params["origClientOrderId"] = client_order_id
        else:
            raise ValueError("Either client_order_id or exchange_order_id is required.")

        payload = self._signed_request("GET", self.order_url, params=params)
        state = self._parse_order_state(payload)
        self._register_state(state)
        return state

    def fetch_open_orders(self, *, symbol: str | None = None) -> tuple[BrokerOrderState, ...]:
        params: dict[str, object] = {}
        if symbol is not None:
            params["symbol"] = symbol.upper()
        payload = self._signed_request("GET", self.open_orders_url, params=params)
        if not isinstance(payload, list):
            raise RuntimeError("Binance open orders response must be a list.")
        states = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            state = self._parse_order_state(item)
            self._register_state(state)
            states.append(state)
        return tuple(states)

    def _settle_entry_fill(self, *, request: OrderRequest, fill: FillReport) -> FillReport:
        if request.order_type is not OrderType.MARKET:
            return fill
        if fill.status is OrderStatus.FILLED and (fill.executed_quantity or fill.quantity) > 0:
            return fill

        state = self.order_manager.wait_for_terminal_state(
            request.order_id,
            timeout_seconds=self.binance.order_fill_timeout_seconds,
        )
        if state is None or not state.status.is_terminal:
            fetched = self.fetch_order(symbol=request.symbol, client_order_id=request.order_id)
            state = fetched or state
        if state is None:
            raise RuntimeError(f"No exchange order state available for submitted order {request.order_id}.")
        if state.filled_quantity <= 0:
            raise RuntimeError(f"Submitted order {request.order_id} did not produce any fill.")
        return self._fill_report_from_state(request=request, state=state)

    def _recover_submission(self, *, request: OrderRequest) -> FillReport | None:
        try:
            state = self.fetch_order(symbol=request.symbol, client_order_id=request.order_id)
        except Exception:
            return None
        if state is None:
            return None
        if state.status in {OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED}:
            return self._fill_report_from_state(request=request, state=state)
        if state.status.is_terminal:
            return self._fill_report_from_state(request=request, state=state)
        return None

    def _build_order_params(self, normalized: NormalizedOrder) -> dict[str, object]:
        request = normalized.request
        if request.side is Side.SHORT and not request.reduce_only:
            raise ValueError("Spot Binance routing does not support opening short positions.")

        order_side = self._binance_side(request.side, reduce_only=request.reduce_only)
        params: dict[str, object] = {
            "symbol": request.symbol.upper(),
            "side": order_side,
            "type": request.order_type.value,
            "quantity": self._format_decimal(float(normalized.quantity)),
            "newClientOrderId": request.order_id,
            "recvWindow": int(request.recv_window or self.binance.user_stream_recv_window),
        }
        if request.order_type is OrderType.MARKET:
            params["newOrderRespType"] = "FULL"
        else:
            params["newOrderRespType"] = "RESULT"
        if normalized.price is not None:
            params["price"] = self._format_decimal(float(normalized.price))
        if normalized.stop_price is not None:
            params["stopPrice"] = self._format_decimal(float(normalized.stop_price))
        if request.time_in_force is not None:
            params["timeInForce"] = request.time_in_force.value
        return params

    def _parse_fill_report(self, *, request: OrderRequest, payload: dict[str, object], simulated: bool) -> FillReport:
        executed_quantity = float(payload.get("executedQty", 0.0))
        cumulative_quote_quantity = float(payload.get("cummulativeQuoteQty", 0.0))
        fills = tuple(
            self._parse_order_fill(item)
            for item in payload.get("fills", [])
            if isinstance(item, dict)
        )
        average_price = 0.0
        if executed_quantity > 0 and cumulative_quote_quantity > 0:
            average_price = cumulative_quote_quantity / executed_quantity
        elif fills:
            quote_total = sum(fill.price * fill.quantity for fill in fills)
            quantity_total = sum(fill.quantity for fill in fills)
            average_price = quote_total / quantity_total if quantity_total > 0 else request.price_reference

        if executed_quantity <= 0 and request.order_type is OrderType.MARKET:
            average_price = request.price_reference

        filled_at = self._timestamp_from_millis(payload.get("transactTime")) or request.submitted_at
        status = OrderStatus(str(payload.get("status", OrderStatus.FILLED.value)).upper())
        return FillReport(
            order_id=request.order_id,
            symbol=request.symbol,
            side=request.side,
            quantity=executed_quantity if executed_quantity > 0 else request.quantity,
            average_price=average_price if average_price > 0 else request.price_reference,
            filled_at=filled_at,
            simulated=simulated,
            exchange_order_id=int(payload["orderId"]) if payload.get("orderId") is not None else None,
            status=status,
            executed_quantity=executed_quantity,
            fills=fills,
        )

    def _fill_report_from_state(self, *, request: OrderRequest, state: BrokerOrderState) -> FillReport:
        return FillReport(
            order_id=request.order_id,
            symbol=state.symbol,
            side=request.side,
            quantity=state.filled_quantity if state.filled_quantity > 0 else request.quantity,
            average_price=state.average_price if state.average_price > 0 else request.price_reference,
            filled_at=state.updated_at or request.submitted_at,
            simulated=False,
            exchange_order_id=state.exchange_order_id,
            status=state.status,
            executed_quantity=state.filled_quantity,
        )

    def _parse_order_state(self, payload: dict[str, object]) -> BrokerOrderState:
        requested_quantity = float(payload.get("origQty", payload.get("executedQty", 0.0)))
        filled_quantity = float(payload.get("executedQty", 0.0))
        cumulative_quote_quantity = float(payload.get("cummulativeQuoteQty", 0.0))
        average_price = 0.0
        if filled_quantity > 0 and cumulative_quote_quantity > 0:
            average_price = cumulative_quote_quantity / filled_quantity
        elif float(payload.get("price", 0.0)) > 0:
            average_price = float(payload["price"])

        created_at = self._timestamp_from_millis(payload.get("time"))
        updated_at = self._timestamp_from_millis(payload.get("updateTime")) or created_at or datetime.now(timezone.utc)
        side_text = str(payload.get("side", "BUY")).upper()
        binance_type = str(payload.get("type", OrderType.MARKET.value)).upper()
        return BrokerOrderState(
            client_order_id=str(payload.get("clientOrderId") or payload.get("origClientOrderId")),
            exchange_order_id=int(payload["orderId"]) if payload.get("orderId") is not None else None,
            symbol=str(payload["symbol"]).upper(),
            side=Side.LONG if side_text == "BUY" else Side.SHORT,
            order_type=OrderType(binance_type),
            requested_quantity=requested_quantity,
            status=OrderStatus(str(payload.get("status", OrderStatus.NEW.value)).upper()),
            filled_quantity=filled_quantity,
            cumulative_quote_quantity=cumulative_quote_quantity,
            average_price=average_price,
            last_price=float(payload.get("stopPrice") or payload.get("price") or average_price or 0.0),
            rejection_reason=None,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _register_state(self, state: BrokerOrderState) -> None:
        synthetic_request = OrderRequest(
            order_id=state.client_order_id,
            symbol=state.symbol,
            side=state.side,
            quantity=state.requested_quantity,
            order_type=state.order_type,
            submitted_at=state.created_at or datetime.now(timezone.utc),
            price_reference=state.average_price or state.last_price or 0.0,
            reason="exchange_sync",
        )
        fill = self._fill_report_from_state(request=synthetic_request, state=state)
        self.order_manager.register_submission_result(synthetic_request, fill)

    def _signed_request(self, method: str, url: str, *, params: dict[str, object]) -> dict[str, object] | list[object]:
        verify = self._verify_setting()
        self._configure_tls_warning_behavior(verify)
        signed_params = dict(params)
        signed_params["timestamp"] = int(datetime.now(timezone.utc).timestamp() * 1000)
        query = urlencode([(key, value) for key, value in signed_params.items() if value is not None], doseq=True)
        signature = hmac.new(self._api_secret_bytes, query.encode("utf-8"), hashlib.sha256).hexdigest()
        signed_params["signature"] = signature
        response = self.session.request(
            method=method.upper(),
            url=url,
            params=signed_params,
            headers={"X-MBX-APIKEY": self.api_key},
            timeout=self.binance.request_timeout_seconds,
            verify=verify,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Binance API error {response.status_code}: {response.text}")
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise RuntimeError("Unexpected Binance API response payload.")
        return payload

    def _verify_setting(self) -> bool | str:
        env_ca_bundle = (os.getenv("BINANCE_CA_BUNDLE_PATH") or "").strip()
        env_ssl_verify = (os.getenv("BINANCE_SSL_VERIFY") or "").strip().lower()
        if env_ca_bundle:
            bundle_path = Path(env_ca_bundle)
            if not bundle_path.is_absolute():
                bundle_path = Path.cwd() / bundle_path
            if not bundle_path.exists():
                raise FileNotFoundError(f"Configured CA bundle not found: {bundle_path}")
            return str(bundle_path)
        if env_ssl_verify:
            if env_ssl_verify in {"false", "0", "no", "off"}:
                return False
            if env_ssl_verify in {"true", "1", "yes", "on"}:
                return True
            raise ValueError(f"Invalid BINANCE_SSL_VERIFY override: {env_ssl_verify!r}")
        if self.binance.ca_bundle_path:
            bundle_path = Path(self.binance.ca_bundle_path)
            if not bundle_path.is_absolute():
                bundle_path = Path.cwd() / bundle_path
            if not bundle_path.exists():
                raise FileNotFoundError(f"Configured CA bundle not found: {bundle_path}")
            return str(bundle_path)
        return bool(self.binance.ssl_verify)

    def _configure_tls_warning_behavior(self, verify_setting: bool | str) -> None:
        if self._warnings_configured:
            return
        if verify_setting is False:
            disable_warnings(InsecureRequestWarning)
        self._warnings_configured = True

    def _emit(self, event_type: str, payload: object) -> None:
        if callable(self.on_event):
            self.on_event(event_type, payload)

    def _binance_side(self, side: Side, *, reduce_only: bool) -> str:
        if side is Side.LONG:
            return "SELL" if reduce_only else "BUY"
        return "BUY" if reduce_only else "SELL"

    def _parse_order_fill(self, payload: dict[str, object]) -> OrderFill:
        return OrderFill(
            price=float(payload["price"]),
            quantity=float(payload["qty"]),
            commission=float(payload.get("commission", 0.0)),
            commission_asset=None if payload.get("commissionAsset") is None else str(payload.get("commissionAsset")),
            trade_id=None if payload.get("tradeId") is None else int(payload["tradeId"]),
        )

    def _timestamp_from_millis(self, value: object) -> datetime | None:
        if value in (None, ""):
            return None
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)

    def _format_decimal(self, value: float) -> str:
        return f"{value:.8f}".rstrip("0").rstrip(".")
