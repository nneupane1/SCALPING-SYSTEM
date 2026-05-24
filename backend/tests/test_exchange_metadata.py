from __future__ import annotations

import unittest
from datetime import datetime

from backend.app.core.models import Side
from backend.app.execution.exchange_metadata import BinanceSymbolMetadata, ExchangeMetadataService
from backend.app.execution.models import OrderRequest, OrderType

from backend.tests.test_exchange_infra import _load_repo_config


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


class ExchangeMetadataTests(unittest.TestCase):
    def test_normalize_order_rounds_quantity_and_stop_price(self) -> None:
        service = ExchangeMetadataService(config=_load_repo_config())
        service.get_symbol_metadata = lambda symbol: _btc_metadata()  # type: ignore[method-assign]
        request = OrderRequest(
            order_id="live-stop-1",
            symbol="BTCUSDT",
            side=Side.LONG,
            quantity=0.012345678,
            order_type=OrderType.STOP_LOSS,
            submitted_at=datetime.utcnow(),
            price_reference=67000.0,
            reason="protective_stop",
            stop_price=66888.887,
            reduce_only=True,
        )

        normalized = service.normalize_order(request)

        self.assertEqual("0.01234", format(normalized.quantity.normalize(), "f"))
        self.assertEqual("66888.88", format(normalized.stop_price.normalize(), "f"))

    def test_normalize_order_rejects_below_min_notional(self) -> None:
        service = ExchangeMetadataService(config=_load_repo_config())
        service.get_symbol_metadata = lambda symbol: _btc_metadata()  # type: ignore[method-assign]
        request = OrderRequest(
            order_id="live-entry-1",
            symbol="BTCUSDT",
            side=Side.LONG,
            quantity=0.00001,
            order_type=OrderType.MARKET,
            submitted_at=datetime.utcnow(),
            price_reference=67000.0,
            reason="strategy_entry",
        )

        with self.assertRaisesRegex(ValueError, "below minimum"):
            service.normalize_order(request)


if __name__ == "__main__":
    unittest.main()
