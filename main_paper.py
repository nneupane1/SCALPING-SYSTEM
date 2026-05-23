"""CLI entry point for paper-trading runtime summary."""

from __future__ import annotations

from backend.app.main import create_app


def main() -> None:
    app = create_app()
    profile = app.config.strategy.resolve_profile(app.config.system.market.execution_timeframe)
    print(f"Runtime mode: {app.config.system.app.mode}")
    print(f"Symbol: {app.config.system.market.symbol}")
    print(f"Execution timeframe: {app.config.system.market.execution_timeframe}")
    print(f"Active profile: {profile.name}")
    print(
        "Research cadence: "
        f"{profile.cadence.expected_trades_per_day_low}-{profile.cadence.expected_trades_per_day_high} trades/day"
    )
    print(f"Initial equity: {app.config.system.account.initial_equity:.2f} {app.config.system.account.base_currency}")
    print("Paper runtime container assembled successfully.")


if __name__ == "__main__":
    main()
