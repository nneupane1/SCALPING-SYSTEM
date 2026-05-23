"""CLI entry point for replay runtime summary."""

from __future__ import annotations

import argparse

from backend.app.main import create_app
from backend.app.replay import ReplayRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Run checkpointed replay over historical candles.")
    parser.add_argument("--symbol", default=None, help="Optional symbol override.")
    parser.add_argument("--start-date", default=None, help="Optional start date override.")
    parser.add_argument("--end-date", default=None, help="Optional end date override.")
    parser.add_argument("--steps", type=int, default=50, help="Maximum steps to process in this run.")
    args = parser.parse_args()

    app = create_app()
    summary = ReplayRunner(app.config).run(
        symbol=args.symbol,
        start_date=args.start_date,
        end_date=args.end_date,
        max_steps=args.steps,
    )
    print(f"Replay summary for {summary.symbol} on {summary.execution_timeframe}")
    print(f"Steps processed this run: {summary.steps_processed}")
    print(f"Current replay index: {summary.current_index}")
    print(f"Closed trades: {summary.closed_trades}")
    print(f"Equity: {summary.current_equity:.2f}")
    print(f"Checkpoint: {summary.checkpoint_path}")


if __name__ == "__main__":
    main()
