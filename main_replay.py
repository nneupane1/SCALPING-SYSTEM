"""CLI entry point for replay runtime summary."""

from __future__ import annotations

import argparse

from backend.app.console import CommandDashboard
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
    with CommandDashboard("Replay Runner", subtitle="Deterministic historical stepping") as dashboard:
        dashboard.emit(
            "context",
            context={
                "symbol": args.symbol or app.config.system.market.symbol,
                "execution_timeframe": app.config.system.market.execution_timeframe,
                "steps_requested": args.steps,
            },
        )
        summary = ReplayRunner(app.config, progress_callback=dashboard.emit).run(
            symbol=args.symbol,
            start_date=args.start_date,
            end_date=args.end_date,
            max_steps=args.steps,
        )
        dashboard.emit(
            "complete",
            status="completed",
            phase="replay command finished",
            detail=str(summary.checkpoint_path),
            metrics={
                "steps_processed": summary.steps_processed,
                "current_index": summary.current_index,
                "closed_trades": summary.closed_trades,
                "equity": f"{summary.current_equity:.2f}",
            },
        )


if __name__ == "__main__":
    main()
