"""Downloads, checkpoints, resumes, validates, saves, and loads Binance OHLCV data."""

from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backend.app.config.models import ConfigBundle, history_path_label, restore_history_path_label
from backend.app.core import JsonCheckpointStore

from .binance_rest import BinanceRestClient


def _fmt(ms: int) -> str:
    return datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def _fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


class MarketDataDownloader:
    """Disk-backed market-data access with resumable partial files."""

    def __init__(
        self,
        config: ConfigBundle,
        client: BinanceRestClient | None = None,
        progress_callback=None,
    ) -> None:
        self.config = config
        self.client = client or BinanceRestClient(config=config)
        self.progress_callback = progress_callback

    def _emit(self, event_type: str, **payload: object) -> None:
        if callable(self.progress_callback):
            self.progress_callback(event_type, **payload)

    def _log(self, message: str, *, level: str = "info") -> None:
        if callable(self.progress_callback):
            self._emit("event", level=level, message=message)
            return
        print(message)

    @staticmethod
    def _to_utc_ms(value: str | pd.Timestamp) -> int:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        return int(timestamp.timestamp() * 1000)

    @staticmethod
    def _validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        required = ["open", "high", "low", "close", "volume"]
        missing = [column for column in required if column not in df.columns]
        if missing:
            raise ValueError(f"Missing OHLCV columns: {missing}")

        if not df.index.is_monotonic_increasing:
            df = df.sort_index()
        if df.index.has_duplicates:
            df = df[~df.index.duplicated(keep="last")]
        df[required] = df[required].apply(pd.to_numeric, errors="raise")
        return df

    @staticmethod
    def _read_ohlcv_csv(path: Path, *, timestamp_only: bool = False) -> pd.DataFrame:
        read_kwargs = {
            "parse_dates": ["timestamp"],
            "on_bad_lines": "skip",
        }
        if timestamp_only:
            read_kwargs["usecols"] = ["timestamp"]
        else:
            read_kwargs["usecols"] = ["timestamp", "open", "high", "low", "close", "volume"]
        try:
            df = pd.read_csv(path, **read_kwargs)
        except (pd.errors.ParserError, ValueError):
            columns = ["timestamp", "open", "high", "low", "close", "volume", "_extra"]
            usecols = [0] if timestamp_only else [0, 1, 2, 3, 4, 5]
            df = pd.read_csv(
                path,
                header=0,
                names=columns,
                usecols=usecols,
                parse_dates=["timestamp"],
                on_bad_lines="skip",
                engine="python",
            )
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df[df["timestamp"].notna()].copy()
        return df

    @staticmethod
    def _interval_delta(interval: str) -> pd.Timedelta:
        unit = interval[-1].lower()
        magnitude = int(interval[:-1])
        if unit == "m":
            return pd.Timedelta(minutes=magnitude)
        if unit == "h":
            return pd.Timedelta(hours=magnitude)
        raise ValueError(f"Unsupported interval: {interval}")

    @classmethod
    def _missing_ranges(
        cls,
        df: pd.DataFrame,
        *,
        interval: str,
        start_bound: pd.Timestamp,
        end_bound: pd.Timestamp,
    ) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
        step = cls._interval_delta(interval)
        expected_last = end_bound - step
        ranges: list[tuple[pd.Timestamp, pd.Timestamp]] = []
        if df.empty:
            if start_bound <= expected_last:
                ranges.append((start_bound, expected_last))
            return ranges

        ordered = df.sort_index()
        first = pd.Timestamp(ordered.index[0])
        last = pd.Timestamp(ordered.index[-1])
        if first > start_bound:
            ranges.append((start_bound, first - step))

        previous = first
        for current in ordered.index[1:]:
            current_ts = pd.Timestamp(current)
            if current_ts - previous > step:
                ranges.append((previous + step, current_ts - step))
            previous = current_ts

        if last < expected_last:
            ranges.append((last + step, expected_last))

        return [(start, end) for start, end in ranges if start <= end]

    def _fetch_missing_range(
        self,
        *,
        symbol: str,
        interval: str,
        range_start: pd.Timestamp,
        range_end: pd.Timestamp,
    ) -> pd.DataFrame:
        step = self._interval_delta(interval)
        current_start = self._to_utc_ms(range_start)
        end_limit = self._to_utc_ms(range_end + step)
        frames: list[pd.DataFrame] = []

        while current_start < end_limit:
            raw = self.client.get_klines(
                symbol=symbol,
                interval=interval,
                start_time=current_start,
                end_time=end_limit,
                limit=self.config.system.binance.historical_limit,
                verbose=False,
            )
            if not raw:
                break
            batch = self.klines_to_df(
                raw,
                closed_only=self.config.system.binance.closed_klines_only,
                announce_removed=False,
            )
            frames.append(batch)
            last_timestamp = pd.Timestamp(batch.index[-1])
            current_start = self._to_utc_ms(last_timestamp + step)
            if len(batch) < self.config.system.binance.historical_limit:
                break

        if not frames:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        combined = pd.concat(frames).sort_index()
        combined = combined.loc[(combined.index >= range_start) & (combined.index <= range_end)]
        return self._validate_ohlcv(combined)

    def _repair_missing_intervals(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        interval: str,
        start_bound: pd.Timestamp,
        end_bound: pd.Timestamp,
    ) -> pd.DataFrame:
        missing_ranges = self._missing_ranges(
            df,
            interval=interval,
            start_bound=start_bound,
            end_bound=end_bound,
        )
        if not missing_ranges:
            return df

        self._log(
            f"Detected {len(missing_ranges)} missing {interval} range(s) during finalization; attempting targeted repair.",
            level="warning",
        )
        repairs: list[pd.DataFrame] = []
        repaired_rows = 0
        for range_start, range_end in missing_ranges:
            repaired = self._fetch_missing_range(
                symbol=symbol,
                interval=interval,
                range_start=range_start,
                range_end=range_end,
            )
            if repaired.empty:
                self._log(
                    f"Unable to backfill missing range {range_start} -> {range_end}.",
                    level="error",
                )
                continue
            repaired_rows += len(repaired)
            repairs.append(repaired)

        if not repairs:
            return df

        merged = pd.concat([df, *repairs]).sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]
        merged = self._validate_ohlcv(merged)
        self._log(
            f"Backfilled {repaired_rows} {interval} candle(s) from Binance during finalization.",
            level="success",
        )
        return merged

    @staticmethod
    def klines_to_df(
        raw: list[list[object]],
        *,
        closed_only: bool = True,
        now_ms: int | None = None,
        announce_removed: bool = True,
    ) -> pd.DataFrame:
        if not raw:
            raise ValueError("No kline data returned from Binance")

        df = pd.DataFrame(
            raw,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_asset_volume",
                "number_of_trades",
                "taker_buy_base",
                "taker_buy_quote",
                "ignore",
            ],
        )

        if closed_only:
            now_ms = now_ms or int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
            df["close_time"] = pd.to_numeric(df["close_time"], errors="raise")
            before = len(df)
            df = df[df["close_time"] <= now_ms]
            removed = before - len(df)
            if removed and announce_removed:
                print(f"Removed {removed} still-forming Binance candle(s)")
            if df.empty:
                raise ValueError("No closed kline data returned from Binance")

        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert(None)
        df.set_index("timestamp", inplace=True)
        return MarketDataDownloader._validate_ohlcv(df)

    def _history_filename(self, symbol: str, interval: str, start_date: str, end_date: str) -> str:
        return (
            f"{symbol}_{interval}_{history_path_label(start_date)}"
            f"_to_{history_path_label(end_date)}.csv"
        )

    def _storage_folder(self, symbol: str, interval: str) -> Path:
        return self.config.system.storage.root / symbol / interval

    def _history_paths(
        self,
        *,
        symbol: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Path]:
        folder = self._storage_folder(symbol, interval)
        filename = self._history_filename(symbol, interval, start_date, end_date)
        download_cfg = self.config.system.downloads.history
        checkpoint_dir = folder / download_cfg.checkpoint_dir
        return {
            "folder": folder,
            "final": folder / filename,
            "partial": folder / f"{filename}{download_cfg.partial_suffix}",
            "checkpoint": checkpoint_dir / f"{filename}{download_cfg.checkpoint_suffix}",
        }

    def _partial_summary(self, partial_path: Path) -> dict[str, int | None]:
        if not partial_path.exists() or partial_path.stat().st_size == 0:
            return {"rows": 0, "last_timestamp_ms": None}
        df = self._read_ohlcv_csv(partial_path)
        if df.empty:
            return {"rows": 0, "last_timestamp_ms": None}
        last_timestamp = pd.Timestamp(df["timestamp"].iloc[-1])
        if last_timestamp.tzinfo is None:
            last_timestamp = last_timestamp.tz_localize("UTC")
        else:
            last_timestamp = last_timestamp.tz_convert("UTC")
        return {"rows": len(df), "last_timestamp_ms": int(last_timestamp.timestamp() * 1000)}

    def _append_batch(self, partial_path: Path, batch_df: pd.DataFrame) -> None:
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not partial_path.exists() or partial_path.stat().st_size == 0
        batch_df.to_csv(partial_path, mode="a", header=write_header)

    def _load_partial(self, partial_path: Path) -> pd.DataFrame:
        df = self._read_ohlcv_csv(partial_path)
        df.set_index("timestamp", inplace=True)
        return self._validate_ohlcv(df)

    def _find_bootstrap_source(
        self,
        *,
        symbol: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> Path | None:
        folder = self._storage_folder(symbol, interval)
        if not folder.exists():
            return None
        target_end_ts = pd.Timestamp(end_date)
        partial_suffix = self.config.system.downloads.history.partial_suffix
        prefix = f"{symbol}_{interval}_{history_path_label(start_date)}_to_"

        best_candidate: Path | None = None
        best_end_ts: pd.Timestamp | None = None
        for candidate in folder.glob(f"{prefix}*.csv"):
            if candidate.name.endswith(partial_suffix):
                continue
            candidate_end_text = restore_history_path_label(candidate.name[len(prefix):-4])
            try:
                candidate_end_ts = pd.Timestamp(candidate_end_text)
            except ValueError:
                continue
            if candidate_end_ts >= target_end_ts:
                continue
            if best_end_ts is None or candidate_end_ts > best_end_ts:
                best_candidate = candidate
                best_end_ts = candidate_end_ts
        return best_candidate

    def _bootstrap_partial_from_completed_history(
        self,
        paths: dict[str, Path],
        *,
        symbol: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> Path | None:
        if paths["partial"].exists() or paths["checkpoint"].exists():
            return None
        source_path = self._find_bootstrap_source(
            symbol=symbol,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
        )
        if source_path is None:
            return None
        paths["partial"].parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, paths["partial"])
        return source_path

    def fetch_full_history(
        self,
        *,
        symbol: str | None = None,
        interval: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Download historical Binance candles with resumable checkpointing."""

        symbol = (symbol or self.config.system.market.symbol).upper()
        interval = interval or self.config.system.binance.default_interval
        start_date = start_date or self.config.system.history.start_date
        end_date = end_date or self.config.system.history.end_date

        start_ts = self._to_utc_ms(start_date)
        end_ts = self._to_utc_ms(end_date)
        paths = self._history_paths(symbol=symbol, interval=interval, start_date=start_date, end_date=end_date)
        paths["folder"].mkdir(parents=True, exist_ok=True)

        download_cfg = self.config.system.downloads.history
        checkpoint_store = JsonCheckpointStore(paths["checkpoint"])

        if download_cfg.resume_enabled and paths["final"].exists():
            self._emit(
                "phase",
                status="cached",
                phase="using cached historical file",
                detail=str(paths["final"]),
            )
            self._emit(
                "progress",
                description=f"Loading cached {symbol} {interval}",
                completed=1,
                total=1,
                status="cached",
            )
            self._emit(
                "metrics",
                metrics={
                    "symbol": symbol,
                    "interval": interval,
                    "range": f"{start_date} -> {end_date}",
                    "storage": paths["final"],
                },
            )
            self._log("Completed historical file already exists.", level="success")
            return self.load_from_csv(paths["final"])

        bootstrap_source = None
        if download_cfg.resume_enabled:
            bootstrap_source = self._bootstrap_partial_from_completed_history(
                paths,
                symbol=symbol,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
            )

        checkpoint = checkpoint_store.read() if download_cfg.resume_enabled else None
        partial_summary = self._partial_summary(paths["partial"]) if download_cfg.resume_enabled else {"rows": 0, "last_timestamp_ms": None}

        current_start = start_ts
        partial_last_ts = partial_summary["last_timestamp_ms"]
        if partial_last_ts is not None:
            current_start = max(current_start, partial_last_ts + 1)
        elif checkpoint and checkpoint.get("next_start_ms"):
            current_start = max(current_start, int(checkpoint["next_start_ms"]))

        total_batches = int(checkpoint.get("batches_downloaded", 0)) if checkpoint else 0
        total_rows = max(int(checkpoint.get("rows_downloaded", 0)) if checkpoint else 0, int(partial_summary["rows"]))

        self._emit(
            "phase",
            status="running",
            phase="downloading historical candles",
            detail=f"{symbol} {interval} | {start_date} -> {end_date}",
        )
        self._emit(
            "metrics",
            metrics={
                "symbol": symbol,
                "interval": interval,
                "range": f"{start_date} -> {end_date}",
                "tls_verify": self.client.describe_verify_mode(),
                "batches": total_batches,
                "rows": total_rows,
            },
        )
        if bootstrap_source is not None:
            self._log(f"Bootstrap source: {bootstrap_source.name}", level="success")
        if current_start > start_ts:
            self._log(f"Resume point: {_fmt(current_start)} | Existing rows: {total_rows}", level="warning")

        start_clock = time.time()
        total_range_ms = max(1, end_ts - start_ts)
        try:
            while current_start < end_ts:
                batch_start = time.time()
                request_batch_number = total_batches + 1
                self._emit(
                    "progress",
                    description=f"Downloading {symbol} {interval}",
                    completed=max(0, current_start - start_ts),
                    total=total_range_ms,
                    status="running",
                )
                self._emit(
                    "metrics",
                    metrics={
                        "batch": request_batch_number,
                        "request_from": _fmt(current_start),
                        "limit": self.config.system.binance.historical_limit,
                        "rows": total_rows,
                        "batches": total_batches,
                    },
                )
                try:
                    raw = self.client.get_klines(
                        symbol=symbol,
                        interval=interval,
                        start_time=current_start,
                        end_time=end_ts,
                        limit=self.config.system.binance.historical_limit,
                        verbose=False,
                    )
                except (Exception, KeyboardInterrupt) as exc:
                    checkpoint_store.write(
                        {
                            "symbol": symbol,
                            "interval": interval,
                            "start_date": start_date,
                            "end_date": end_date,
                            "next_start_ms": current_start,
                            "next_start_time": _fmt(current_start),
                            "batches_downloaded": total_batches,
                            "rows_downloaded": total_rows,
                            "completed": False,
                            "last_error": str(exc),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    self._emit(
                        "phase",
                        status="failed",
                        phase="download interrupted",
                        detail=str(paths["checkpoint"]),
                    )
                    self._log(f"Download interrupted. Checkpoint saved: {paths['checkpoint']}", level="error")
                    raise

                if not raw:
                    self._log("No more data returned from Binance. Stopping.", level="warning")
                    break

                batch_df = self.klines_to_df(
                    raw,
                    closed_only=self.config.system.binance.closed_klines_only,
                    announce_removed=self.progress_callback is None,
                )
                self._append_batch(paths["partial"], batch_df)

                first_ts = self._to_utc_ms(batch_df.index[0])
                last_ts = self._to_utc_ms(batch_df.index[-1])
                current_start = last_ts + 1
                total_batches += 1
                total_rows += len(batch_df)

                if total_batches % download_cfg.save_every_batches == 0:
                    checkpoint_store.write(
                        {
                            "symbol": symbol,
                            "interval": interval,
                            "start_date": start_date,
                            "end_date": end_date,
                            "next_start_ms": current_start,
                            "next_start_time": _fmt(current_start),
                            "last_timestamp_ms": last_ts,
                            "last_timestamp": _fmt(last_ts),
                            "batches_downloaded": total_batches,
                            "rows_downloaded": total_rows,
                            "partial_csv": str(paths["partial"]),
                            "final_csv": str(paths["final"]),
                            "completed": False,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )

                total_time = time.time() - start_clock
                batch_time = time.time() - batch_start
                progress_pct = min(100, ((last_ts - start_ts) / total_range_ms) * 100)
                remaining_pct = max(0.01, 100 - progress_pct)
                eta_seconds = total_time * (remaining_pct / max(progress_pct, 0.0001))
                self._emit(
                    "progress",
                    description=f"Downloading {symbol} {interval}",
                    completed=max(0, last_ts - start_ts),
                    total=total_range_ms,
                    status="running",
                )
                self._emit(
                    "metrics",
                    metrics={
                        "batch": total_batches,
                        "batch_rows": len(batch_df),
                        "rows": total_rows,
                        "progress_pct": f"{progress_pct:.2f}%",
                        "remaining_pct": f"{remaining_pct:.2f}%",
                        "elapsed": _fmt_duration(total_time),
                        "eta": _fmt_duration(eta_seconds),
                        "window": f"{_fmt(first_ts)} -> {_fmt(last_ts)}",
                    },
                )
                if total_batches % download_cfg.status_every_batches == 0 or total_batches == 1:
                    self._log(
                        f"Batch {total_batches} saved | window {_fmt(first_ts)} -> {_fmt(last_ts)} | "
                        f"rows {len(batch_df)} | total {total_rows}",
                        level="info",
                    )

                throttle = self.config.system.binance.throttle_seconds
                if throttle > 0:
                    time.sleep(throttle)

            if not paths["partial"].exists():
                raise FileNotFoundError(f"No partial download file found: {paths['partial']}")

            self._emit(
                "phase",
                status="finalizing",
                phase="finalizing historical file",
                detail=str(paths["final"]),
            )
            df = self._load_partial(paths["partial"])
            before_dedupe = len(df)
            df = df[~df.index.duplicated(keep="last")].sort_index()
            start_bound = pd.Timestamp(start_date)
            end_bound = pd.Timestamp(end_date)
            df = df.loc[(df.index >= start_bound) & (df.index < end_bound)]
            df = self._repair_missing_intervals(
                df,
                symbol=symbol,
                interval=interval,
                start_bound=start_bound,
                end_bound=end_bound,
            )
            duplicates_removed = before_dedupe - len(df)
            df.to_csv(paths["final"])

            checkpoint_store.write(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "start_date": start_date,
                    "end_date": end_date,
                    "next_start_ms": end_ts,
                    "next_start_time": _fmt(end_ts),
                    "batches_downloaded": total_batches,
                    "rows_downloaded": len(df),
                    "partial_csv": str(paths["partial"]),
                    "final_csv": str(paths["final"]),
                    "completed": True,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

            if download_cfg.cleanup_partial_on_complete and paths["partial"].exists():
                paths["partial"].unlink()

            total_time = time.time() - start_clock
            self._emit(
                "complete",
                status="completed",
                phase="historical download complete",
                detail=str(paths["final"]),
                metrics={
                    "rows": len(df),
                    "duplicates_removed": duplicates_removed,
                    "elapsed_minutes": f"{total_time / 60:.2f}",
                    "checkpoint": paths["checkpoint"],
                },
            )
            self._log(f"Saved final CSV: {paths['final']}", level="success")
            return df
        finally:
            pass

    def fetch_recent(
        self,
        *,
        symbol: str | None = None,
        interval: str | None = None,
        limit: int | None = None,
        verbose: bool = True,
    ) -> pd.DataFrame:
        symbol = (symbol or self.config.system.market.symbol).upper()
        interval = interval or self.config.system.binance.default_interval
        limit = limit or self.config.system.binance.recent_limit
        raw = self.client.get_klines(
            symbol=symbol,
            interval=interval,
            limit=limit,
            verbose=verbose,
        )
        return self.klines_to_df(
            raw,
            closed_only=self.config.system.binance.closed_klines_only,
            announce_removed=self.progress_callback is None,
        )

    def load_from_csv(self, filepath: str | Path) -> pd.DataFrame:
        path = Path(filepath)
        self._emit(
            "phase",
            status="running",
            phase="loading local csv",
            detail=str(path),
        )
        start = time.time()
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")
        df = self._read_ohlcv_csv(path)
        df.set_index("timestamp", inplace=True)
        df = self._validate_ohlcv(df)
        self._emit(
            "metrics",
            metrics={
                "source_rows": len(df),
                "load_time_sec": f"{time.time() - start:.2f}",
            },
        )
        return df

    def realtime_runtime_path(self, *, symbol: str, interval: str | None = None) -> Path:
        base_interval = interval or self.config.system.market.base_timeframe
        folder = self._storage_folder(symbol.upper(), base_interval)
        return folder / f"{symbol.upper()}_{base_interval}_live_runtime.csv"

    def append_realtime_history(
        self,
        *,
        symbol: str,
        frame: pd.DataFrame,
        interval: str | None = None,
        last_persisted_at: pd.Timestamp | None = None,
    ) -> pd.Timestamp | None:
        if frame.empty:
            return last_persisted_at
        path = self.realtime_runtime_path(symbol=symbol, interval=interval)
        path.parent.mkdir(parents=True, exist_ok=True)
        append_df = frame.sort_index()
        required_columns = ["open", "high", "low", "close", "volume"]
        append_df = append_df.loc[:, [column for column in required_columns if column in append_df.columns]]
        if last_persisted_at is not None:
            append_df = append_df.loc[append_df.index > last_persisted_at]
        if append_df.empty:
            return last_persisted_at
        write_header = not path.exists() or path.stat().st_size == 0
        append_df.to_csv(path, mode="a", header=write_header)
        return append_df.index.max()

    def latest_timestamp_in_csv(self, path: str | Path) -> pd.Timestamp | None:
        csv_path = Path(path)
        if not csv_path.exists() or csv_path.stat().st_size == 0:
            return None
        df = self._read_ohlcv_csv(csv_path, timestamp_only=True)
        if df.empty:
            return None
        return pd.Timestamp(df["timestamp"].iloc[-1])
