"""CLI entry point for checkpointed historical backtests."""

from __future__ import annotations

import argparse

from backend.app.backtest import BacktestRunner
from backend.app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the checkpointed backtest runner.")
    parser.add_argument("--symbol", default=None, help="Optional symbol override.")
    parser.add_argument("--start-date", default=None, help="Optional start date override.")
    parser.add_argument("--end-date", default=None, help="Optional end date override.")
    args = parser.parse_args()

    app = create_app()
    runner = BacktestRunner(app.config)
    summary = runner.run(
        symbol=args.symbol,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    print(f"Backtest completed for {summary.symbol} on {summary.execution_timeframe}")
    print(f"Range: {summary.start_date} -> {summary.end_date}")
    print(f"Steps processed: {summary.steps_processed}")
    print(f"Closed trades: {summary.closed_trades}")
    print(f"Current equity: {summary.current_equity:.2f}")
    print(f"Realized PnL: {summary.realized_pnl:.2f}")
    print(f"Outputs: {summary.output_dir}")


if __name__ == "__main__":
    main()
