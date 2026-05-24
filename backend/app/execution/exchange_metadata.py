"""Binance symbol metadata, filter parsing, and request normalization."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from pathlib import Path
from urllib.parse import urljoin

import requests
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning

from backend.app.config.models import BinanceConfig, ConfigBundle

from .models import OrderRequest, OrderType


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True)
class PriceFilter:
    min_price: Decimal
    max_price: Decimal
    tick_size: Decimal


@dataclass(frozen=True)
class LotSizeFilter:
    min_qty: Decimal
    max_qty: Decimal
    step_size: Decimal


@dataclass(frozen=True)
class NotionalFilter:
    min_notional: Decimal | None
    max_notional: Decimal | None
    apply_min_to_market: bool
    apply_max_to_market: bool


@dataclass(frozen=True)
class BinanceSymbolMetadata:
    symbol: str
    status: str
    base_asset: str
    quote_asset: str
    order_types: tuple[str, ...]
    is_spot_trading_allowed: bool
    base_asset_precision: int
    quote_asset_precision: int
    price_filter: PriceFilter | None
    lot_size_filter: LotSizeFilter | None
    market_lot_size_filter: LotSizeFilter | None
    notional_filter: NotionalFilter | None

    @classmethod
    def from_exchange_info_symbol(cls, payload: dict[str, object]) -> "BinanceSymbolMetadata":
        filters = {
            str(item.get("filterType")): item
            for item in payload.get("filters", [])
            if isinstance(item, dict) and item.get("filterType") is not None
        }
        price_payload = filters.get("PRICE_FILTER")
        lot_payload = filters.get("LOT_SIZE")
        market_lot_payload = filters.get("MARKET_LOT_SIZE")
        notional_payload = filters.get("NOTIONAL")
        min_notional_payload = filters.get("MIN_NOTIONAL")

        price_filter = (
            None
            if price_payload is None
            else PriceFilter(
                min_price=_decimal(price_payload.get("minPrice", "0")),
                max_price=_decimal(price_payload.get("maxPrice", "0")),
                tick_size=_decimal(price_payload.get("tickSize", "0")),
            )
        )
        lot_size_filter = (
            None
            if lot_payload is None
            else LotSizeFilter(
                min_qty=_decimal(lot_payload.get("minQty", "0")),
                max_qty=_decimal(lot_payload.get("maxQty", "0")),
                step_size=_decimal(lot_payload.get("stepSize", "0")),
            )
        )
        market_lot_size_filter = (
            None
            if market_lot_payload is None
            else LotSizeFilter(
                min_qty=_decimal(market_lot_payload.get("minQty", "0")),
                max_qty=_decimal(market_lot_payload.get("maxQty", "0")),
                step_size=_decimal(market_lot_payload.get("stepSize", "0")),
            )
        )

        notional_filter = None
        if notional_payload is not None:
            notional_filter = NotionalFilter(
                min_notional=_decimal(notional_payload.get("minNotional")) if notional_payload.get("minNotional") is not None else None,
                max_notional=_decimal(notional_payload.get("maxNotional")) if notional_payload.get("maxNotional") is not None else None,
                apply_min_to_market=bool(notional_payload.get("applyMinToMarket", False)),
                apply_max_to_market=bool(notional_payload.get("applyMaxToMarket", False)),
            )
        elif min_notional_payload is not None:
            notional_filter = NotionalFilter(
                min_notional=_decimal(min_notional_payload.get("minNotional")) if min_notional_payload.get("minNotional") is not None else None,
                max_notional=None,
                apply_min_to_market=bool(min_notional_payload.get("applyToMarket", False)),
                apply_max_to_market=False,
            )

        return cls(
            symbol=str(payload["symbol"]).upper(),
            status=str(payload.get("status", "")),
            base_asset=str(payload.get("baseAsset", "")).upper(),
            quote_asset=str(payload.get("quoteAsset", "")).upper(),
            order_types=tuple(str(item).upper() for item in payload.get("orderTypes", [])),
            is_spot_trading_allowed=bool(payload.get("isSpotTradingAllowed", False)),
            base_asset_precision=int(payload.get("baseAssetPrecision", 8)),
            quote_asset_precision=int(payload.get("quoteAssetPrecision", 8)),
            price_filter=price_filter,
            lot_size_filter=lot_size_filter,
            market_lot_size_filter=market_lot_size_filter,
            notional_filter=notional_filter,
        )


@dataclass(frozen=True)
class NormalizedOrder:
    request: OrderRequest
    quantity: Decimal
    price: Decimal | None
    stop_price: Decimal | None
    estimated_notional: Decimal
    metadata: BinanceSymbolMetadata


class ExchangeMetadataService:
    """Fetch and cache Binance symbol metadata, then normalize orders against it."""

    def __init__(
        self,
        *,
        config: ConfigBundle,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config
        self.binance = config.system.binance
        self.session = session or requests.Session()
        self._warnings_configured = False
        self.exchange_info_url = urljoin(
            self.binance.base_url.rstrip("/") + "/",
            self.binance.exchange_info_path.lstrip("/"),
        )
        self._symbol_cache: dict[str, tuple[float, BinanceSymbolMetadata]] = {}

    def get_symbol_metadata(self, symbol: str) -> BinanceSymbolMetadata:
        symbol = symbol.upper()
        cached = self._symbol_cache.get(symbol)
        now = time.time()
        if cached is not None and now - cached[0] <= self.binance.exchange_info_cache_seconds:
            return cached[1]

        verify = self._verify_setting(self.binance)
        self._configure_tls_warning_behavior(verify)
        response = self.session.get(
            self.exchange_info_url,
            params={"symbol": symbol},
            timeout=self.binance.request_timeout_seconds,
            verify=verify,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Binance exchangeInfo error {response.status_code}: {response.text}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected Binance exchangeInfo payload.")
        symbols = payload.get("symbols")
        if not isinstance(symbols, list) or not symbols:
            raise RuntimeError(f"Binance exchangeInfo returned no symbol metadata for {symbol}.")
        metadata = BinanceSymbolMetadata.from_exchange_info_symbol(symbols[0])
        self._symbol_cache[symbol] = (now, metadata)
        return metadata

    def normalize_order(self, request: OrderRequest) -> NormalizedOrder:
        metadata = self.get_symbol_metadata(request.symbol)
        self._validate_symbol_ready(metadata=metadata, request=request)

        quantity_filter = self._quantity_filter(metadata=metadata, request=request)
        rounded_quantity = self._round_down(value=_decimal(request.quantity), step=quantity_filter.step_size)
        if rounded_quantity <= 0:
            raise ValueError(f"Rounded quantity became non-positive for {request.symbol}.")
        self._validate_quantity(rounded_quantity, quantity_filter, request.symbol)

        rounded_price = None
        rounded_stop = None
        price_filter = metadata.price_filter
        if request.price is not None:
            if price_filter is None:
                raise ValueError(f"No PRICE_FILTER metadata available for priced order on {request.symbol}.")
            rounded_price = self._round_down(value=_decimal(request.price), step=price_filter.tick_size)
            self._validate_price(rounded_price, price_filter, request.symbol, field_name="price")
        if request.stop_price is not None:
            if price_filter is None:
                raise ValueError(f"No PRICE_FILTER metadata available for stop order on {request.symbol}.")
            rounded_stop = self._round_down(value=_decimal(request.stop_price), step=price_filter.tick_size)
            self._validate_price(rounded_stop, price_filter, request.symbol, field_name="stopPrice")

        reference_price = self._estimate_reference_price(
            request=request,
            rounded_price=rounded_price,
            rounded_stop=rounded_stop,
        )
        estimated_notional = rounded_quantity * reference_price
        self._validate_notional(
            estimated_notional=estimated_notional,
            request=request,
            metadata=metadata,
            symbol=request.symbol,
        )

        return NormalizedOrder(
            request=request,
            quantity=rounded_quantity,
            price=rounded_price,
            stop_price=rounded_stop,
            estimated_notional=estimated_notional,
            metadata=metadata,
        )

    def _validate_symbol_ready(self, *, metadata: BinanceSymbolMetadata, request: OrderRequest) -> None:
        if metadata.status.upper() != "TRADING":
            raise ValueError(f"{metadata.symbol} is not in TRADING status: {metadata.status}")
        if not metadata.is_spot_trading_allowed:
            raise ValueError(f"{metadata.symbol} is not spot-trading enabled.")
        if request.order_type.value not in metadata.order_types:
            raise ValueError(
                f"{request.order_type.value} is not supported for {metadata.symbol}; supported={metadata.order_types}"
            )

    def _quantity_filter(self, *, metadata: BinanceSymbolMetadata, request: OrderRequest) -> LotSizeFilter:
        if request.order_type is OrderType.MARKET and metadata.market_lot_size_filter is not None:
            return metadata.market_lot_size_filter
        if metadata.lot_size_filter is None:
            raise ValueError(f"No LOT_SIZE metadata available for {request.symbol}.")
        return metadata.lot_size_filter

    def _validate_quantity(self, quantity: Decimal, quantity_filter: LotSizeFilter, symbol: str) -> None:
        if quantity_filter.min_qty > 0 and quantity < quantity_filter.min_qty:
            raise ValueError(f"{symbol} quantity {quantity} is below minQty {quantity_filter.min_qty}.")
        if quantity_filter.max_qty > 0 and quantity > quantity_filter.max_qty:
            raise ValueError(f"{symbol} quantity {quantity} exceeds maxQty {quantity_filter.max_qty}.")

    def _validate_price(
        self,
        price: Decimal,
        price_filter: PriceFilter,
        symbol: str,
        *,
        field_name: str,
    ) -> None:
        if price_filter.min_price > 0 and price < price_filter.min_price:
            raise ValueError(f"{symbol} {field_name} {price} is below minPrice {price_filter.min_price}.")
        if price_filter.max_price > 0 and price > price_filter.max_price:
            raise ValueError(f"{symbol} {field_name} {price} exceeds maxPrice {price_filter.max_price}.")

    def _validate_notional(
        self,
        *,
        estimated_notional: Decimal,
        request: OrderRequest,
        metadata: BinanceSymbolMetadata,
        symbol: str,
    ) -> None:
        notional_filter = metadata.notional_filter
        if notional_filter is None:
            return
        is_market = request.order_type is OrderType.MARKET
        if notional_filter.min_notional is not None and (
            not is_market or notional_filter.apply_min_to_market
        ):
            if estimated_notional < notional_filter.min_notional:
                raise ValueError(
                    f"{symbol} notional {estimated_notional} is below minimum {notional_filter.min_notional}."
                )
        if notional_filter.max_notional is not None and (
            not is_market or notional_filter.apply_max_to_market
        ):
            if estimated_notional > notional_filter.max_notional:
                raise ValueError(
                    f"{symbol} notional {estimated_notional} exceeds maximum {notional_filter.max_notional}."
                )

    def _estimate_reference_price(
        self,
        *,
        request: OrderRequest,
        rounded_price: Decimal | None,
        rounded_stop: Decimal | None,
    ) -> Decimal:
        if rounded_price is not None and rounded_price > 0:
            return rounded_price
        if rounded_stop is not None and rounded_stop > 0:
            return rounded_stop
        return _decimal(request.price_reference)

    def _round_down(self, *, value: Decimal, step: Decimal) -> Decimal:
        if step <= 0:
            return value
        return (value / step).to_integral_value(rounding=ROUND_DOWN) * step

    def _round_up(self, *, value: Decimal, step: Decimal) -> Decimal:
        if step <= 0:
            return value
        return (value / step).to_integral_value(rounding=ROUND_UP) * step

    def _verify_setting(self, binance: BinanceConfig) -> bool | str:
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
        if binance.ca_bundle_path:
            bundle_path = Path(binance.ca_bundle_path)
            if not bundle_path.is_absolute():
                bundle_path = Path.cwd() / bundle_path
            if not bundle_path.exists():
                raise FileNotFoundError(f"Configured CA bundle not found: {bundle_path}")
            return str(bundle_path)
        return bool(binance.ssl_verify)

    def _configure_tls_warning_behavior(self, verify_setting: bool | str) -> None:
        if self._warnings_configured:
            return
        if verify_setting is False:
            disable_warnings(InsecureRequestWarning)
        self._warnings_configured = True
