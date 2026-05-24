"""CLI entry point for checkpointed historical backtests."""

from __future__ import annotations

import argparse

from backend.app.backtest import BacktestRunner
from backend.app.console import CommandDashboard
from backend.app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the checkpointed backtest runner.")
    parser.add_argument("--symbol", default=None, help="Optional symbol override.")
    parser.add_argument("--start-date", default=None, help="Optional start date override.")
    parser.add_argument("--end-date", default=None, help="Optional end date override.")
    args = parser.parse_args()

    app = create_app()
    with CommandDashboard("Backtest Runner", subtitle="Checkpointed historical simulation") as dashboard:
        dashboard.emit(
            "context",
            context={
                "symbol": args.symbol or app.config.system.market.symbol,
                "execution_timeframe": app.config.system.market.execution_timeframe,
                "range": (
                    f"{args.start_date or app.config.system.history.start_date} -> "
                    f"{args.end_date or app.config.system.history.end_date}"
                ),
            },
        )
        runner = BacktestRunner(app.config, progress_callback=dashboard.emit)
        summary = runner.run(
            symbol=args.symbol,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        dashboard.emit(
            "complete",
            status="completed",
            phase="backtest command finished",
            detail=str(summary.output_dir),
            metrics={
                "steps": summary.steps_processed,
                "closed_trades": summary.closed_trades,
                "equity": f"{summary.current_equity:.2f}",
                "realized_pnl": f"{summary.realized_pnl:.2f}",
            },
        )


if __name__ == "__main__":
    main()
