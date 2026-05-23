"""Replay simulator that pipes snapshots through the trading engine."""

from __future__ import annotations

from backend.app.core.engine import EngineCycleResult, TradingEngine

from .replay_engine import ReplayEngine


class ReplaySimulator:
    """Run the engine against replay snapshots."""

    def __init__(self, replay_engine: ReplayEngine, trading_engine: TradingEngine) -> None:
        self.replay_engine = replay_engine
        self.trading_engine = trading_engine

    def step(self) -> EngineCycleResult | None:
        snapshot = self.replay_engine.step()
        if snapshot is None:
            return None
        return self.trading_engine.process_snapshot(snapshot)

    def run_all(self) -> tuple[EngineCycleResult, ...]:
        results: list[EngineCycleResult] = []
        while self.replay_engine.has_next():
            result = self.step()
            if result is not None:
                results.append(result)
        return tuple(results)

