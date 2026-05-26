from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.app.config.models import ConfigBundle, RiskConfig, StrategyConfig, SystemConfig
from backend.app.core.models import MarketSnapshot, OpenPosition, RiskPlan, Side, TradeSignal
from backend.app.core.orchestrator import build_runtime

from backend.tests.helpers import make_candle


class TradingEngineClockTests(unittest.TestCase):
    def test_manage_snapshot_advances_position_only_on_new_execution_close(self) -> None:
        config = _build_config()
        runtime = build_runtime(config)

        position = OpenPosition(
            symbol="BTCUSDT",
            timeframe="5m",
            side=Side.LONG,
            opened_at=datetime(2026, 1, 5, 10, 6, tzinfo=timezone.utc),
            entry_price=105.6,
            stop_price=104.8,
            initial_stop_price=104.8,
            initial_quantity=10.0,
            remaining_quantity=10.0,
            risk_plan=RiskPlan(
                equity=25_000.0,
                risk_fraction=0.005,
                risk_amount=125.0,
                risk_per_unit=0.8,
                position_size=10.0,
                first_partial_at_price=106.4,
                first_partial_fraction=0.5,
                breakeven_after_partial=True,
            ),
            source_signal=TradeSignal(
                strategy_name="pullback_scalp",
                symbol="BTCUSDT",
                timeframe="5m",
                side=Side.LONG,
                generated_at=datetime(2026, 1, 5, 10, 6, tzinfo=timezone.utc),
                entry_price=105.6,
                stop_price=104.8,
                first_target_price=106.4,
                confidence=0.7,
                reasons=("test",),
                metadata={"execution_close": datetime(2026, 1, 5, 10, 5, tzinfo=timezone.utc).isoformat()},
            ),
        )
        runtime.portfolio_manager.open_position(position)

        execution_candles = (
            make_candle(
                minute_offset=0,
                open_price=105.0,
                high=105.8,
                low=104.9,
                close=105.4,
                volume=10.0,
                timeframe="5m",
            ),
        )
        trigger_candles = (
            make_candle(
                minute_offset=5,
                open_price=105.4,
                high=105.7,
                low=105.35,
                close=105.55,
                volume=3.0,
                timeframe="1m",
            ),
            make_candle(
                minute_offset=6,
                open_price=105.55,
                high=105.75,
                low=105.5,
                close=105.6,
                volume=3.0,
                timeframe="1m",
            ),
        )

        first_snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            generated_at=trigger_candles[0].close_time,
            candles={"1m": trigger_candles[:1], "5m": execution_candles},
        )
        second_snapshot = MarketSnapshot(
            symbol="BTCUSDT",
            generated_at=trigger_candles[1].close_time,
            candles={"1m": trigger_candles, "5m": execution_candles},
        )

        first_decisions = runtime.engine.manage_snapshot(first_snapshot)
        second_decisions = runtime.engine.manage_snapshot(second_snapshot)

        self.assertEqual((), first_decisions)
        self.assertEqual((), second_decisions)
        self.assertEqual(1, position.bars_held)


def _build_config() -> ConfigBundle:
    return ConfigBundle(
        system=SystemConfig.from_mapping(
            {
                "app": {"name": "test", "mode": "backtest", "debug": False},
                "account": {"initial_equity": 25_000, "base_currency": "EUR"},
                "market": {
                    "symbol": "BTCUSDT",
                    "base_timeframe": "1m",
                    "execution_timeframe": "5m",
                    "context_timeframes": [],
                    "supported_execution_timeframes": ["5m"],
                },
                "sessions": {"enabled": False, "timezone": "UTC", "active_windows": []},
                "storage": {"root": "data_storage", "cache_limit": 1000},
                "resample": {"closed": "left", "label": "right", "drop_incomplete": True},
                "history": {
                    "start_date": "2024-01-01 08:00:00",
                    "end_date": "2024-01-01 08:20:00",
                },
                "backtest": {"enabled": True},
                "replay": {"enabled": True},
                "paper": {"enabled": True},
                "live": {"enabled": True},
                "transport": {"websocket_broadcast_buffer": 10},
            }
        ),
        strategy=StrategyConfig.from_mapping(
            {
                "scanner": {
                    "min_impulse_body_ratio": 1.3,
                    "min_volume_ratio": 1.0,
                    "max_pullback_depth_ratio": 0.8,
                    "max_pullback_body_ratio": 0.8,
                    "min_pullback_bars": 1,
                    "max_pullback_bars": 1,
                    "compression_lookback": 2,
                },
                "strategy": {
                    "name": "pullback_scalp",
                    "allow_long": True,
                    "allow_short": True,
                    "trigger": {
                        "timeframe": "1m",
                        "require_breakout_close": True,
                        "min_close_position": 0.55,
                        "min_body_ratio": 1.0,
                        "stop_buffer_ratio": 0.04,
                    },
                },
                "filters": {
                    "context": {"enabled": False},
                    "market_state": {"enabled": False},
                    "quality": {"enabled": False},
                    "session": {"enabled": False},
                },
            }
        ),
        risk=RiskConfig.from_mapping(
            {
                "risk": {
                    "risk_per_trade": 0.005,
                    "max_open_positions": 1,
                    "max_daily_loss_r": 3.0,
                    "max_consecutive_losses": 4,
                },
                "management": {
                    "first_partial_at_r": 1.0,
                    "first_partial_size": 0.5,
                    "move_stop_to_breakeven_after_first_partial": True,
                    "trailing_lookback_bars": 1,
                    "early_exit_after_bars": 3,
                    "early_exit_min_progress_r": 0.2,
                    "early_exit_max_adverse_close_r": -0.35,
                },
                "execution": {"allow_live_orders": False, "max_slippage_bps": 5.0},
            }
        ),
    )


if __name__ == "__main__":
    unittest.main()
