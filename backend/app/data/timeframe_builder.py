"""Builds configured OHLCV timeframes from the base one-minute market data."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from backend.app.config.models import ConfigBundle, history_path_label


class TimeframeBuilder:
    """Build and persist configured timeframes from a canonical `1m` DataFrame."""

    def __init__(self, config: ConfigBundle, progress_callback=None) -> None:
        self.config = config
        self.resample_config = config.system.resample
        self.progress_callback = progress_callback
        self._last_incomplete_signature: tuple[int, str] | None = None

    def _emit(self, event_type: str, **payload: object) -> None:
        if callable(self.progress_callback):
            self.progress_callback(event_type, **payload)

    def _log(self, message: str, *, level: str = "info") -> None:
        if callable(self.progress_callback):
            self._emit("event", level=level, message=message)
            return
        print(message)

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
            signature = (removed, close_cutoff.isoformat())
            if signature != self._last_incomplete_signature:
                self._log(
                    f"Removed {removed} incomplete resampled candle(s); "
                    f"latest usable close: {close_cutoff}",
                    level="warning",
                )
                self._last_incomplete_signature = signature
        return df_resampled

    def _expected_rows_per_bucket(self, rule: str) -> int:
        base_rule = self._to_pandas_rule(self.config.system.market.base_timeframe)
        base_seconds = int(pd.Timedelta(pd.tseries.frequencies.to_offset(base_rule)).total_seconds())
        target_seconds = int(pd.Timedelta(pd.tseries.frequencies.to_offset(rule)).total_seconds())
        if target_seconds % base_seconds != 0:
            raise ValueError("Target timeframe must be an integer multiple of the base timeframe.")
        return target_seconds // base_seconds

    def resample(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        start = time.time()
        self._emit(
            "phase",
            status="running",
            phase="resampling timeframe",
            detail=f"building {rule} from {self.config.system.market.base_timeframe}",
        )
        pandas_rule = self._to_pandas_rule(rule)
        source = df.sort_index()
        expected_rows = self._expected_rows_per_bucket(pandas_rule)
        bucket_counts = source.resample(
            pandas_rule,
            closed=self.resample_config.closed,
            label=self.resample_config.label,
        ).size()
        df_resampled = (
            source.resample(
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
        complete_labels = bucket_counts[bucket_counts == expected_rows].index
        before_gap_filter = len(df_resampled)
        df_resampled = df_resampled.loc[df_resampled.index.isin(complete_labels)]
        removed_for_internal_gaps = before_gap_filter - len(df_resampled)
        if removed_for_internal_gaps:
            self._log(
                f"Removed {removed_for_internal_gaps} resampled candle(s) with internal base-timeframe gaps.",
                level="warning",
            )
        df_resampled = self._drop_incomplete_resampled_candles(source, df_resampled)
        self._emit(
            "metrics",
            metrics={
                "active_timeframe": rule,
                f"{rule}_rows": len(df_resampled),
                f"{rule}_build_sec": f"{time.time() - start:.2f}",
            },
        )
        return df_resampled

    def build_timeframes(self, df_1m: pd.DataFrame) -> dict[str, pd.DataFrame]:
        market = self.config.system.market
        derived = {
            timeframe
            for timeframe in (
                market.execution_timeframe,
                *market.context_timeframes,
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
        self._emit(
            "phase",
            status="running",
            phase="resampling market history",
            detail=f"{symbol} | {start_date} -> {end_date}",
        )
        frames = self.build_timeframes(df_1m)
        total_frames = len(frames)
        for index, (timeframe, frame) in enumerate(frames.items(), start=1):
            folder = root / symbol / timeframe
            folder.mkdir(parents=True, exist_ok=True)
            path = (
                folder
                / f"{symbol}_{timeframe}_{history_path_label(start_date)}_to_{history_path_label(end_date)}.csv"
            )
            t0 = time.time()
            frame.to_csv(path, index_label="timestamp")
            self._emit(
                "progress",
                description=f"Saving resampled frames for {symbol}",
                completed=index,
                total=total_frames,
                status="running",
            )
            self._emit(
                "metrics",
                metrics={
                    "symbol": symbol,
                    "range": f"{start_date} -> {end_date}",
                    "saved_timeframe": timeframe,
                    "saved_rows": len(frame),
                    "save_time_sec": f"{time.time() - t0:.2f}",
                },
            )
            self._log(f"Saved {timeframe} -> {path}", level="success")
        self._emit(
            "complete",
            status="completed",
            phase="resampling complete",
            detail=f"{symbol} | {start_date} -> {end_date}",
            metrics={
                "elapsed_sec": f"{time.time() - overall_start:.2f}",
                **{f"{timeframe}_rows": len(frame) for timeframe, frame in frames.items()},
            },
        )
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
