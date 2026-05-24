"""CLI entry point for forward paper-trading execution."""

from __future__ import annotations

import argparse

from backend.app.console import CommandDashboard
from backend.app.live import ForwardRunner
from backend.app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the forward paper-trading loop.")
    parser.add_argument("--symbol", default=None, help="Optional symbol override.")
    parser.add_argument("--polls", type=int, default=1, help="Maximum market-data polls to run.")
    args = parser.parse_args()

    app = create_app(mode_override="paper")
    profile = app.config.strategy.resolve_profile(app.config.system.market.execution_timeframe)
    with CommandDashboard("Paper Runner", subtitle="Forward simulated execution") as dashboard:
        dashboard.emit(
            "context",
            context={
                "mode": app.config.system.app.mode,
                "symbol": args.symbol or app.config.system.market.symbol,
                "execution_timeframe": app.config.system.market.execution_timeframe,
                "context_timeframes": ", ".join(app.config.system.market.context_timeframes) or "none",
                "profile": profile.name,
                "cadence": (
                    f"{profile.cadence.expected_trades_per_day_low}-"
                    f"{profile.cadence.expected_trades_per_day_high} trades/day"
                ),
            },
        )
        runner = ForwardRunner(
            app.config,
            mode="paper",
            broadcaster=app.websocket,
            progress_callback=dashboard.emit,
        )
        summary = runner.run(symbol=args.symbol, max_polls=args.polls)
        dashboard.emit(
            "complete",
            status="completed",
            phase="paper command finished",
            detail=str(summary.checkpoint_path),
            metrics={
                "polls": summary.polls_processed,
                "snapshots": summary.snapshots_processed,
                "closed_trades": summary.closed_trades,
                "equity": f"{summary.current_equity:.2f}",
            },
        )


if __name__ == "__main__":
    main()
