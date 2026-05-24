"""CLI entry point for forward live-scanning execution."""

from __future__ import annotations

import argparse

from backend.app.console import CommandDashboard
from backend.app.live import StreamingLiveRunner
from backend.app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the websocket-driven live-scanning loop.")
    parser.add_argument("--symbol", default=None, help="Optional symbol override.")
    parser.add_argument(
        "--polls",
        type=int,
        default=1,
        help="Maximum closed 1m websocket candles to process before stopping.",
    )
    args = parser.parse_args()

    app = create_app(mode_override="live")
    profile = app.config.strategy.resolve_profile(app.config.system.market.execution_timeframe)
    broker_label = "binance live" if app.config.risk.execution.allow_live_orders else "paper safety gate"
    with CommandDashboard("Live Runner", subtitle="Websocket live scanning and exchange-aware execution") as dashboard:
        dashboard.emit(
            "context",
            context={
                "mode": app.config.system.app.mode,
                "symbol": args.symbol or app.config.system.market.symbol,
                "execution_timeframe": app.config.system.market.execution_timeframe,
                "context_timeframes": ", ".join(app.config.system.market.context_timeframes) or "none",
                "profile": profile.name,
                "runner_emphasis": profile.cadence.runner_emphasis,
                "live_orders_enabled": app.config.risk.execution.allow_live_orders,
                "broker": broker_label,
            },
        )
        if not app.config.risk.execution.allow_live_orders:
            dashboard.emit(
                "event",
                level="warning",
                message="Safety gate active: live broker submission is disabled. Orders remain simulated.",
            )
        summary = StreamingLiveRunner(
            app.config,
            broadcaster=app.websocket,
            progress_callback=dashboard.emit,
        ).run(symbol=args.symbol, max_events=args.polls)
        dashboard.emit(
            "complete",
            status="completed",
            phase="live command finished",
            detail=str(summary.checkpoint_path),
            metrics={
                "market_events": summary.market_events_processed,
                "snapshots": summary.snapshots_processed,
                "closed_trades": summary.closed_trades,
                "equity": f"{summary.current_equity:.2f}",
                "broker": broker_label,
            },
        )


if __name__ == "__main__":
    main()
