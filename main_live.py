"""CLI entry point for live-trading readiness checks."""

from __future__ import annotations

from backend.app.main import create_app


def main() -> None:
    app = create_app()
    profile = app.config.strategy.resolve_profile(app.config.system.market.execution_timeframe)
    print(f"Configured mode: {app.config.system.app.mode}")
    print(f"Execution timeframe: {app.config.system.market.execution_timeframe}")
    print(f"Active profile: {profile.name} | runner emphasis: {profile.cadence.runner_emphasis}")
    print(f"Live orders enabled: {app.config.risk.execution.allow_live_orders}")
    print("Live runtime assembly succeeded.")
    if not app.config.risk.execution.allow_live_orders:
        print("Safety gate: live broker submission is disabled by config.")
    print("Authenticated broker integration is not implemented yet.")


if __name__ == "__main__":
    main()
