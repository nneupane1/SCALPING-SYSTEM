from __future__ import annotations

import os
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from backend.app.config.loader import load_config_bundle
from backend.app.core.models import Side
from backend.app.data.binance_ws import BinanceWebSocketClient
from backend.app.execution.broker_binance import BinanceBroker
from backend.app.execution.exchange_metadata import BinanceSymbolMetadata, NormalizedOrder
from backend.app.execution.models import OrderRequest, OrderType, TimeInForce
from backend.app.execution.order_manager import OrderManager
from backend.app.execution.user_stream import _parse_execution_report


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_repo_config():
    root = _repo_root()
    return load_config_bundle(
        root / "backend/app/config/system.example.yaml",
        root / "backend/app/config/strategy.example.yaml",
        root / "backend/app/config/risk.example.yaml",
    )


def _btc_metadata() -> BinanceSymbolMetadata:
    return BinanceSymbolMetadata.from_exchange_info_symbol(
        {
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "baseAsset": "BTC",
            "quoteAsset": "USDT",
            "baseAssetPrecision": 8,
            "quoteAssetPrecision": 8,
            "orderTypes": ["MARKET", "STOP_LOSS"],
            "isSpotTradingAllowed": True,
            "filters": [
                {
                    "filterType": "PRICE_FILTER",
                    "minPrice": "0.01",
                    "maxPrice": "1000000.00",
                    "tickSize": "0.01",
                },
                {
                    "filterType": "LOT_SIZE",
                    "minQty": "0.00001000",
                    "maxQty": "100.00000000",
                    "stepSize": "0.00001000",
                },
                {
                    "filterType": "MARKET_LOT_SIZE",
                    "minQty": "0.00001000",
                    "maxQty": "100.00000000",
                    "stepSize": "0.00001000",
                },
                {
                    "filterType": "MIN_NOTIONAL",
                    "minNotional": "10.00",
                    "applyToMarket": True,
                    "avgPriceMins": 5,
                },
            ],
        }
    )


class ExchangeInfrastructureTests(unittest.TestCase):
    def test_public_ws_decoder_returns_closed_kline_event(self) -> None:
        decoder = BinanceWebSocketClient()
        event = decoder.decode_closed_kline_event(
            {
                "stream": "btcusdt@kline_1m",
                "data": {
                    "e": "kline",
                    "s": "BTCUSDT",
                    "k": {
                        "t": 1716507600000,
                        "T": 1716507659999,
                        "s": "BTCUSDT",
                        "i": "1m",
                        "o": "67000.0",
                        "c": "67010.5",
                        "h": "67020.0",
                        "l": "66990.0",
                        "v": "12.3",
                        "n": 42,
                        "x": True,
                    },
                },
            }
        )

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual("BTCUSDT", event.symbol)
        self.assertEqual("1m", event.interval)
        self.assertEqual(42, event.trade_count)
        self.assertEqual(67010.5, event.close)

    def test_user_stream_execution_report_is_normalized(self) -> None:
        event = _parse_execution_report(
            {
                "e": "executionReport",
                "E": 1716507660000,
                "s": "BTCUSDT",
                "c": "live-20260524010101-000001",
                "S": "BUY",
                "o": "MARKET",
                "x": "TRADE",
                "X": "FILLED",
                "i": 123456789,
                "l": "0.01000000",
                "z": "0.01000000",
                "L": "67015.0",
                "Z": "670.15000000",
                "T": 1716507660000,
                "r": "NONE",
            }
        )

        self.assertEqual("live-20260524010101-000001", event.client_order_id)
        self.assertEqual(Side.LONG, event.side)
        self.assertEqual(OrderType.MARKET, event.order_type)
        self.assertEqual(0.01, event.cumulative_filled_quantity)

    def test_binance_broker_maps_entry_and_reduce_only_sides(self) -> None:
        config = _load_repo_config()
        order_manager = OrderManager(mode="live")
        with patch.dict(
            os.environ,
            {"BINANCE_API_KEY": "dummy", "BINANCE_API_SECRET": "dummy-secret"},
            clear=False,
        ):
            broker = BinanceBroker(config=config, order_manager=order_manager)
        metadata = _btc_metadata()

        entry_request = OrderRequest(
            order_id="live-entry-1",
            symbol="BTCUSDT",
            side=Side.LONG,
            quantity=0.01,
            order_type=OrderType.MARKET,
            submitted_at=datetime.utcnow(),
            price_reference=67000.0,
            reason="strategy_entry",
        )
        exit_request = OrderRequest(
            order_id="live-exit-1",
            symbol="BTCUSDT",
            side=Side.LONG,
            quantity=0.01,
            order_type=OrderType.STOP_LOSS,
            submitted_at=datetime.utcnow(),
            price_reference=66800.0,
            reason="protective_stop",
            stop_price=66800.0,
            reduce_only=True,
            time_in_force=TimeInForce.GTC,
        )

        entry_params = broker._build_order_params(
            NormalizedOrder(
                request=entry_request,
                quantity=Decimal("0.01"),
                price=None,
                stop_price=None,
                estimated_notional=Decimal("670"),
                metadata=metadata,
            )
        )
        exit_params = broker._build_order_params(
            NormalizedOrder(
                request=exit_request,
                quantity=Decimal("0.01"),
                price=None,
                stop_price=Decimal("66800.00"),
                estimated_notional=Decimal("668"),
                metadata=metadata,
            )
        )

        self.assertEqual("BUY", entry_params["side"])
        self.assertEqual("FULL", entry_params["newOrderRespType"])
        self.assertEqual("SELL", exit_params["side"])
        self.assertEqual("66800", exit_params["stopPrice"])
        self.assertEqual("GTC", exit_params["timeInForce"])


if __name__ == "__main__":
    unittest.main()
