"""CLI entry point for canonical Binance history bootstrap planning."""

from __future__ import annotations

import argparse

from backend.app.console import CommandDashboard
from backend.app.data import MarketDataDownloader
from backend.app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Download checkpointed Binance history.")
    parser.add_argument("--symbol", default=None, help="Optional symbol override for display purposes.")
    parser.add_argument("--interval", default=None, help="Optional interval override.")
    parser.add_argument("--start-date", default=None, help="Optional start date override.")
    parser.add_argument("--end-date", default=None, help="Optional end date override.")
    args = parser.parse_args()
    app = create_app()
    interval = args.interval or app.config.system.market.base_timeframe
    symbol = args.symbol or app.config.system.market.symbol
    start_date = args.start_date or app.config.system.history.start_date
    end_date = args.end_date or app.config.system.history.end_date
    with CommandDashboard("Historical Download", subtitle="Binance OHLCV bootstrap") as dashboard:
        dashboard.emit(
            "context",
            context={
                "symbol": symbol,
                "interval": interval,
                "range": f"{start_date} -> {end_date}",
                "storage_root": app.config.system.storage.root,
            },
        )
        downloader = MarketDataDownloader(app.config, progress_callback=dashboard.emit)
        frame = downloader.fetch_full_history(
            symbol=symbol,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
        )
        dashboard.emit(
            "complete",
            status="completed",
            phase="download command finished",
            detail=f"{symbol} {interval}",
            metrics={
                "rows": len(frame),
                "latest": frame.index.max(),
                "storage_root": app.config.system.storage.root,
            },
        )


if __name__ == "__main__":
    main()
