"""CLI entry point for multi-symbol Binance history bootstrap."""

from __future__ import annotations

import argparse

from backend.app.console import CommandDashboard
from backend.app.data import MarketDataDownloader
from backend.app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Download checkpointed Binance history for a watchlist.")
    parser.add_argument(
        "--symbols",
        default=None,
        help="Optional comma-separated watchlist override, for example BTCUSDT,ETHUSDT,SOLUSDT.",
    )
    parser.add_argument("--interval", default=None, help="Optional interval override.")
    parser.add_argument("--start-date", default=None, help="Optional start date override.")
    parser.add_argument("--end-date", default=None, help="Optional end date override.")
    args = parser.parse_args()

    app = create_app()
    interval = args.interval or app.config.system.market.base_timeframe
    start_date = args.start_date or app.config.system.history.start_date
    end_date = args.end_date or app.config.system.history.end_date
    symbols = app.config.system.market.resolved_symbols(args.symbols)

    with CommandDashboard("Historical Watchlist Download", subtitle="Binance OHLCV bootstrap") as dashboard:
        dashboard.emit(
            "context",
            context={
                "symbols": ", ".join(symbols),
                "watchlist_size": len(symbols),
                "interval": interval,
                "range": f"{start_date} -> {end_date}",
                "storage_root": app.config.system.storage.root,
            },
        )
        downloader = MarketDataDownloader(app.config, progress_callback=dashboard.emit)
        total_rows = 0
        latest_by_symbol: dict[str, object] = {}
        for index, symbol in enumerate(symbols, start=1):
            dashboard.emit(
                "phase",
                status="running",
                phase=f"downloading {symbol}",
                detail=f"{index}/{len(symbols)} | {interval} | {start_date} -> {end_date}",
            )
            dashboard.emit(
                "progress",
                description=f"Watchlist symbol {index}/{len(symbols)}",
                completed=index - 1,
                total=len(symbols),
                status="running",
            )
            frame = downloader.fetch_full_history(
                symbol=symbol,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
            )
            total_rows += len(frame)
            latest_by_symbol[symbol] = frame.index.max() if not frame.empty else None
            dashboard.emit(
                "event",
                level="success",
                message=f"{symbol} complete | rows {len(frame):,} | latest {latest_by_symbol[symbol]}",
            )

        dashboard.emit(
            "progress",
            description=f"Downloaded {len(symbols)} symbols",
            completed=len(symbols),
            total=len(symbols),
            status="completed",
        )
        dashboard.emit(
            "complete",
            status="completed",
            phase="watchlist download finished",
            detail=", ".join(symbols),
            metrics={
                "symbols": len(symbols),
                "total_rows": f"{total_rows:,}",
                "latest_written": " | ".join(f"{symbol}: {latest_by_symbol[symbol]}" for symbol in symbols),
                "storage_root": app.config.system.storage.root,
            },
        )


if __name__ == "__main__":
    main()
