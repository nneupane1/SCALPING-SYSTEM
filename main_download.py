"""CLI entry point for canonical Binance history bootstrap planning."""

from __future__ import annotations

import argparse

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
    downloader = MarketDataDownloader(app.config)
    interval = args.interval or app.config.system.market.base_timeframe
    frame = downloader.fetch_full_history(
        symbol=args.symbol,
        interval=interval,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    print(f"\nDownload complete | rows={len(frame)} | latest={frame.index.max()}")
    print(f"Storage root: {app.config.system.storage.root}")


if __name__ == "__main__":
    main()
