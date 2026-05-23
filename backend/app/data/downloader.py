"""Downloads, checkpoints, resumes, validates, saves, and loads Binance OHLCV data."""

from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backend.app.config.models import ConfigBundle
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

    def __init__(self, config: ConfigBundle, client: BinanceRestClient | None = None) -> None:
        self.config = config
        self.client = client or BinanceRestClient(config=config)

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
    def klines_to_df(
        raw: list[list[object]],
        *,
        closed_only: bool = True,
        now_ms: int | None = None,
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
            now_ms = now_ms or int(pd.Timestamp.utcnow().timestamp() * 1000)
            df["close_time"] = pd.to_numeric(df["close_time"], errors="raise")
            before = len(df)
            df = df[df["close_time"] <= now_ms]
            removed = before - len(df)
            if removed:
                print(f"Removed {removed} still-forming Binance candle(s)")
            if df.empty:
                raise ValueError("No closed kline data returned from Binance")

        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert(None)
        df.set_index("timestamp", inplace=True)
        return MarketDataDownloader._validate_ohlcv(df)

    def _history_filename(self, symbol: str, interval: str, start_date: str, end_date: str) -> str:
        return f"{symbol}_{interval}_{start_date}_to_{end_date}.csv"

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
        df = pd.read_csv(partial_path, parse_dates=["timestamp"])
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
        df = pd.read_csv(partial_path, parse_dates=["timestamp"])
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
        prefix = f"{symbol}_{interval}_{start_date}_to_"

        best_candidate: Path | None = None
        best_end_ts: pd.Timestamp | None = None
        for candidate in folder.glob(f"{prefix}*.csv"):
            if candidate.name.endswith(partial_suffix):
                continue
            candidate_end_text = candidate.name[len(prefix):-4]
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
            print("\nCompleted historical file already exists.")
            print(f"Using cached file: {paths['final']}")
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

        print(f"\nStarting download: {symbol} | {interval}")
        print(f"Range: {start_date} -> {end_date}")
        print(f"TLS verify: {self.client.describe_verify_mode()}")
        if bootstrap_source is not None:
            print(f"Bootstrap source: {bootstrap_source.name}")
        if current_start > start_ts:
            print(f"Resume point: {_fmt(current_start)} | Existing rows: {total_rows}")

        start_clock = time.time()
        total_range_ms = max(1, end_ts - start_ts)
        try:
            while current_start < end_ts:
                batch_start = time.time()
                request_batch_number = total_batches + 1
                print(
                    f"\nRequesting batch {request_batch_number} | from {_fmt(current_start)} "
                    f"| limit={self.config.system.binance.historical_limit}"
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
                    print(f"Download interrupted. Checkpoint saved: {paths['checkpoint']}")
                    raise

                if not raw:
                    print("No more data returned from Binance. Stopping.")
                    break

                batch_df = self.klines_to_df(
                    raw,
                    closed_only=self.config.system.binance.closed_klines_only,
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
                if total_batches % download_cfg.status_every_batches == 0 or total_batches == 1:
                    print(f"Batch {total_batches} saved")
                    print(f"  Window: {_fmt(first_ts)} -> {_fmt(last_ts)}")
                    print(f"  Rows this batch: {len(batch_df)} | Total rows: {total_rows}")
                    print(f"  Progress: {progress_pct:.2f}% | Remaining: {remaining_pct:.2f}%")
                    print(
                        f"  Timing: batch {_fmt_duration(batch_time)} | "
                        f"elapsed {_fmt_duration(total_time)} | ETA {_fmt_duration(eta_seconds)}"
                    )

                throttle = self.config.system.binance.throttle_seconds
                if throttle > 0:
                    time.sleep(throttle)

            if not paths["partial"].exists():
                raise FileNotFoundError(f"No partial download file found: {paths['partial']}")

            print("\nDownload loop complete. Finalizing CSV...")
            df = self._load_partial(paths["partial"])
            before_dedupe = len(df)
            df = df[~df.index.duplicated(keep="last")].sort_index()
            df = df.loc[start_date:end_date]
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
            print(f"Saved final CSV: {paths['final']}")
            print(f"Duplicate rows removed: {duplicates_removed}")
            print(f"TOTAL TIME: {total_time / 60:.2f} minutes")
            print(f"Total candles: {len(df)}")
            return df
        finally:
            pass

    def fetch_recent(
        self,
        *,
        symbol: str | None = None,
        interval: str | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        symbol = (symbol or self.config.system.market.symbol).upper()
        interval = interval or self.config.system.binance.default_interval
        limit = limit or self.config.system.binance.recent_limit
        raw = self.client.get_klines(
            symbol=symbol,
            interval=interval,
            limit=limit,
            verbose=True,
        )
        return self.klines_to_df(
            raw,
            closed_only=self.config.system.binance.closed_klines_only,
        )

    def load_from_csv(self, filepath: str | Path) -> pd.DataFrame:
        path = Path(filepath)
        print(f"Loading: {path}")
        start = time.time()
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")
        df = pd.read_csv(path, parse_dates=["timestamp"])
        df.set_index("timestamp", inplace=True)
        df = self._validate_ohlcv(df)
        print(f"Loaded in {time.time() - start:.2f} sec")
        return df

