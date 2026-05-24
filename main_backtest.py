"""CLI entry point for checkpointed historical backtests."""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.app.backtest import BacktestRunner
from backend.app.console import CommandDashboard, start_backtest_viewer_launcher
from backend.app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the checkpointed backtest runner.")
    parser.add_argument("--symbol", default=None, help="Optional symbol override.")
    parser.add_argument("--start-date", default=None, help="Optional start date override.")
    parser.add_argument("--end-date", default=None, help="Optional end date override.")
    parser.add_argument(
        "--no-viewer",
        action="store_true",
        help="Do not auto-open the local /backtest browser viewer.",
    )
    parser.add_argument(
        "--viewer-url",
        default="http://127.0.0.1:3000/backtest",
        help="Viewer URL to open automatically when the backtest starts.",
    )
    args = parser.parse_args()

    app = create_app()
    active_windows = " | ".join(
        f"{window.name} {window.start}-{window.end}"
        for window in app.config.system.sessions.active_windows
    )
    with CommandDashboard("Backtest Runner", subtitle="Checkpointed historical simulation") as dashboard:
        if not args.no_viewer:
            start_backtest_viewer_launcher(
                emit=lambda message: dashboard.emit("event", level="info", message=message),
                url=args.viewer_url,
                repo_root=Path(__file__).resolve().parent,
            )
        dashboard.emit(
            "context",
            context={
                "symbol": args.symbol or app.config.system.market.symbol,
                "execution_timeframe": app.config.system.market.execution_timeframe,
                "base_timeframe": app.config.system.market.base_timeframe,
                "range": (
                    f"{args.start_date or app.config.system.history.start_date} -> "
                    f"{args.end_date or app.config.system.history.end_date}"
                ),
                "session_timezone": app.config.system.sessions.timezone,
                "active_sessions": active_windows or "disabled",
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
                "gap_windows": summary.gap_windows,
                "gap_blocked_steps": summary.gap_blocked_steps,
                "gap_forced_exits": summary.gap_forced_exits,
            },
        )


if __name__ == "__main__":
    main()
