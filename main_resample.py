"""CLI entry point for resample-planning output."""

from __future__ import annotations

import argparse

from backend.app.console import CommandDashboard
from backend.app.config.models import history_path_label
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
    base_path = (
        app.config.system.storage.root
        / symbol
        / app.config.system.market.base_timeframe
        / (
            f"{symbol}_{app.config.system.market.base_timeframe}_"
            f"{history_path_label(start_date)}_to_{history_path_label(end_date)}.csv"
        )
    )
    legacy_base_path = (
        app.config.system.storage.root
        / symbol
        / app.config.system.market.base_timeframe
        / f"{symbol}_{app.config.system.market.base_timeframe}_{start_date}_to_{end_date}.csv"
    )
    legacy_date_only_base_path = (
        app.config.system.storage.root
        / symbol
        / app.config.system.market.base_timeframe
        / (
            f"{symbol}_{app.config.system.market.base_timeframe}_"
            f"{str(start_date).split(' ', maxsplit=1)[0]}_to_{str(end_date).split(' ', maxsplit=1)[0]}.csv"
        )
    )
    if not base_path.exists() and legacy_base_path.exists():
        base_path = legacy_base_path
    elif not base_path.exists() and legacy_date_only_base_path.exists():
        base_path = legacy_date_only_base_path
    with CommandDashboard("Resample Pipeline", subtitle="Canonical 1m -> derived frames") as dashboard:
        dashboard.emit(
            "context",
            context={
                "symbol": symbol,
                "base_timeframe": app.config.system.market.base_timeframe,
                "execution_timeframe": app.config.system.market.execution_timeframe,
                "context_timeframes": ", ".join(app.config.system.market.context_timeframes) or "none",
                "range": f"{start_date} -> {end_date}",
            },
        )
        downloader = MarketDataDownloader(app.config, progress_callback=dashboard.emit)
        df_1m = downloader.load_from_csv(base_path)
        frames = TimeframeBuilder(app.config, progress_callback=dashboard.emit).build_timeframes_and_save(
            df_1m,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        dashboard.emit(
            "complete",
            status="completed",
            phase="resample command finished",
            detail=f"{symbol} | {start_date} -> {end_date}",
            metrics={f"{timeframe}_rows": len(frame) for timeframe, frame in frames.items()},
        )


if __name__ == "__main__":
    main()
