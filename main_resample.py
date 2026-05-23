"""CLI entry point for resample-planning output."""

from __future__ import annotations

import argparse

from backend.app.data import MarketDataDownloader, TimeframeBuilder
from backend.app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Resample saved 1m history into configured higher timeframes.")
    parser.add_argument("--symbol", default=None, help="Optional symbol override.")
    parser.add_argument("--start-date", default=None, help="Optional start date override.")
    parser.add_argument("--end-date", default=None, help="Optional end date override.")
    args = parser.parse_args()

    app = create_app()
    symbol = args.symbol or app.config.system.market.symbol
    start_date = args.start_date or app.config.system.history.start_date
    end_date = args.end_date or app.config.system.history.end_date

    downloader = MarketDataDownloader(app.config)
    base_path = (
        app.config.system.storage.root
        / symbol
        / app.config.system.market.base_timeframe
        / f"{symbol}_{app.config.system.market.base_timeframe}_{start_date}_to_{end_date}.csv"
    )
    df_1m = downloader.load_from_csv(base_path)
    frames = TimeframeBuilder(app.config).build_timeframes_and_save(
        df_1m,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
    )
    print("\nResample complete:")
    for timeframe, frame in frames.items():
        print(f"  {timeframe}: {len(frame)} rows")


if __name__ == "__main__":
    main()
