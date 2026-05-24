from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from backend.app.config.loader import load_config_bundle


class ConfigLoaderTests(unittest.TestCase):
    def test_load_config_bundle_honors_env_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            system_path = root / "system.yaml"
            strategy_path = root / "strategy.yaml"
            risk_path = root / "risk.yaml"

            system_path.write_text(
                "\n".join(
                    [
                        "app:",
                        "  name: test",
                        "  mode: paper",
                        "account:",
                        "  initial_equity: 1000",
                        "market:",
                        "  symbol: BTCUSDT",
                        "  base_timeframe: 1m",
                        "  execution_timeframe: 5m",
                        "sessions:",
                        "  enabled: true",
                        "  timezone: UTC",
                        "  active_windows: []",
                        "storage:",
                        f"  root: {str(root / 'data_storage').replace(chr(92), '/')}",
                        "transport:",
                        "  websocket_broadcast_buffer: 10",
                    ]
                ),
                encoding="utf-8",
            )
            strategy_path.write_text(
                "\n".join(
                    [
                        "scanner:",
                        "  min_impulse_body_ratio: 1.5",
                        "  min_volume_ratio: 1.2",
                        "  max_pullback_depth_ratio: 0.8",
                        "  max_pullback_body_ratio: 0.75",
                        "  min_pullback_bars: 1",
                        "  max_pullback_bars: 3",
                        "  compression_lookback: 5",
                        "strategy:",
                        "  name: pullback_scalp",
                        "  allow_long: true",
                        "  allow_short: true",
                    ]
                ),
                encoding="utf-8",
            )
            risk_path.write_text(
                "\n".join(
                    [
                        "risk:",
                        "  risk_per_trade: 0.005",
                        "management: {}",
                        "execution: {}",
                    ]
                ),
                encoding="utf-8",
            )

            original_system = os.environ.get("TRADING_SYSTEM_CONFIG")
            original_mode = os.environ.get("TRADING_SYSTEM_MODE")
            os.environ["TRADING_SYSTEM_CONFIG"] = str(system_path)
            os.environ["TRADING_SYSTEM_MODE"] = "live"
            try:
                config = load_config_bundle(
                    root / "does-not-matter.yaml",
                    strategy_path,
                    risk_path,
                )
            finally:
                self._restore("TRADING_SYSTEM_CONFIG", original_system)
                self._restore("TRADING_SYSTEM_MODE", original_mode)

            self.assertEqual("live", config.system.app.mode)
            self.assertEqual("BTCUSDT", config.system.market.symbol)

    @staticmethod
    def _restore(name: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
