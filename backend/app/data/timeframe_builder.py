"""Builds configured OHLCV timeframes from the base one-minute market data."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from backend.app.config.models import ConfigBundle


class TimeframeBuilder:
    """Build and persist configured timeframes from a canonical `1m` DataFrame."""

    def __init__(self, config: ConfigBundle) -> None:
        self.config = config
        self.resample_config = config.system.resample

    def _source_close_cutoff(self, df: pd.DataFrame) -> pd.Timestamp:
        base_rule = self._to_pandas_rule(self.config.system.market.base_timeframe)
        base_offset = pd.tseries.frequencies.to_offset(base_rule)
        return df.index.max() + base_offset

    def _drop_incomplete_resampled_candles(
        self,
        df_source: pd.DataFrame,
        df_resampled: pd.DataFrame,
    ) -> pd.DataFrame:
        if not self.resample_config.drop_incomplete:
            return df_resampled
        close_cutoff = self._source_close_cutoff(df_source)
        before = len(df_resampled)
        df_resampled = df_resampled.loc[df_resampled.index <= close_cutoff]
        removed = before - len(df_resampled)
        if removed:
            print(
                f"Removed {removed} incomplete resampled candle(s); "
                f"latest usable close: {close_cutoff}"
            )
        return df_resampled

    def resample(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        start = time.time()
        print(f"\nResampling -> {rule}")
        pandas_rule = self._to_pandas_rule(rule)
        df_resampled = (
            df.resample(
                pandas_rule,
                closed=self.resample_config.closed,
                label=self.resample_config.label,
            )
            .agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            })
            .dropna()
        )
        df_resampled = self._drop_incomplete_resampled_candles(df, df_resampled)
        print(f"Done: {rule} | rows: {len(df_resampled)} | Time: {time.time() - start:.2f}s")
        return df_resampled

    def build_timeframes(self, df_1m: pd.DataFrame) -> dict[str, pd.DataFrame]:
        market = self.config.system.market
        derived = {
            timeframe
            for timeframe in (
                market.execution_timeframe,
                *market.context_timeframes,
                *market.supported_execution_timeframes,
            )
            if timeframe != market.base_timeframe
        }
        result = {market.base_timeframe: df_1m}
        for timeframe in sorted(derived, key=self._sort_key):
            result[timeframe] = self.resample(df_1m, timeframe)
        return result

    def build_timeframes_and_save(
        self,
        df_1m: pd.DataFrame,
        *,
        symbol: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        base_path: str | Path | None = None,
    ) -> dict[str, pd.DataFrame]:
        symbol = (symbol or self.config.system.market.symbol).upper()
        start_date = start_date or self.config.system.history.start_date
        end_date = end_date or self.config.system.history.end_date
        root = Path(base_path or self.config.system.storage.root)

        overall_start = time.time()
        print(f"\nStarting resampling pipeline for {symbol}")
        print(f"Range: {start_date} -> {end_date}")
        frames = self.build_timeframes(df_1m)
        for timeframe, frame in frames.items():
            folder = root / symbol / timeframe
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{symbol}_{timeframe}_{start_date}_to_{end_date}.csv"
            t0 = time.time()
            frame.to_csv(path)
            print(f"Saved {timeframe} -> {path} | Time: {time.time() - t0:.2f}s")
        print(f"\nResampling pipeline completed in {time.time() - overall_start:.2f}s")
        for timeframe, frame in frames.items():
            print(f"  {timeframe}: {len(frame)} rows")
        return frames

    def _sort_key(self, timeframe: str) -> int:
        unit = timeframe[-1].lower()
        magnitude = int(timeframe[:-1])
        if unit == "m":
            return magnitude
        if unit == "h":
            return magnitude * 60
        return magnitude

    def _to_pandas_rule(self, timeframe: str) -> str:
        unit = timeframe[-1].lower()
        magnitude = int(timeframe[:-1])
        if unit == "m":
            return f"{magnitude}min"
        if unit == "h":
            return f"{magnitude}h"
        raise ValueError(f"Unsupported timeframe for pandas resample: {timeframe}")
