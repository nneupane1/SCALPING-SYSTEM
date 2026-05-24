"""Session-aware context for intraday trade shaping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from backend.app.config.models import SessionsConfig, StrategyFilterConfig
from backend.app.core.models import MarketSnapshot


@dataclass(frozen=True)
class SessionAssessment:
    """Interpret where the current candle lives inside the trading day."""

    active: bool
    session_name: str | None
    phase: str
    confidence_adjustment: float
    risk_multiplier: float
    reasons: tuple[str, ...]


def assess_session(
    *,
    snapshot: MarketSnapshot,
    sessions_config: SessionsConfig,
    tuning_config: StrategyFilterConfig.SessionTuningConfig,
) -> SessionAssessment:
    """Shape signals by session timing without changing the pattern logic."""

    if not tuning_config.enabled or not sessions_config.enabled:
        return SessionAssessment(
            active=True,
            session_name=None,
            phase="disabled",
            confidence_adjustment=0.0,
            risk_multiplier=1.0,
            reasons=(),
        )

    local_timestamp = snapshot.generated_at.astimezone(ZoneInfo(sessions_config.timezone))
    active_window = None
    for window in sessions_config.active_windows:
        start_time = _parse_clock(window.start)
        end_time = _parse_clock(window.end)
        if _time_in_window(local_timestamp.timetz().replace(tzinfo=None), start_time, end_time):
            active_window = window
            break

    if active_window is None:
        return SessionAssessment(
            active=not tuning_config.block_outside_sessions,
            session_name=None,
            phase="outside",
            confidence_adjustment=-tuning_config.outside_confidence_penalty,
            risk_multiplier=tuning_config.outside_risk_multiplier,
            reasons=("outside configured active sessions",),
        )

    start_time = _parse_clock(active_window.start)
    end_time = _parse_clock(active_window.end)
    elapsed_minutes = _minutes_since(local_timestamp, start_time)
    total_minutes = _window_minutes(start_time, end_time)
    remaining_minutes = max(0, total_minutes - elapsed_minutes)

    if elapsed_minutes < tuning_config.opening_minutes:
        return SessionAssessment(
            active=True,
            session_name=active_window.name,
            phase="opening",
            confidence_adjustment=tuning_config.opening_confidence_bonus,
            risk_multiplier=tuning_config.opening_risk_multiplier,
            reasons=(f"{active_window.name} session is in its opening drive",),
        )
    if remaining_minutes <= tuning_config.closing_buffer_minutes:
        return SessionAssessment(
            active=True,
            session_name=active_window.name,
            phase="closing",
            confidence_adjustment=-tuning_config.closing_confidence_penalty,
            risk_multiplier=tuning_config.closing_risk_multiplier,
            reasons=(f"{active_window.name} session is in its late-stage slowdown",),
        )
    return SessionAssessment(
        active=True,
        session_name=active_window.name,
        phase="core",
        confidence_adjustment=tuning_config.core_confidence_adjustment,
        risk_multiplier=tuning_config.core_risk_multiplier,
        reasons=(f"{active_window.name} session is in its core trading window",),
    )


def _parse_clock(value: str) -> time:
    hour_text, minute_text = value.split(":", maxsplit=1)
    return time(hour=int(hour_text), minute=int(minute_text))


def _time_in_window(current: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def _minutes_since(timestamp: datetime, start: time) -> int:
    start_minutes = start.hour * 60 + start.minute
    current_minutes = timestamp.hour * 60 + timestamp.minute
    if current_minutes < start_minutes:
        current_minutes += 24 * 60
    return current_minutes - start_minutes


def _window_minutes(start: time, end: time) -> int:
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    if end_minutes < start_minutes:
        end_minutes += 24 * 60
    return end_minutes - start_minutes
