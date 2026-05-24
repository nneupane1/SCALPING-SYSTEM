"""Data structures for scanner diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.core.models import Side


@dataclass(frozen=True)
class ImpulseAssessment:
    """Quality assessment for the impulse leg."""

    valid: bool
    side: Side
    body_ratio: float
    volume_ratio: float
    range_ratio: float
    close_position: float
    efficiency: float
    quality_score: float
    tier: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PullbackAssessment:
    """Quality assessment for the pullback leg."""

    valid: bool
    retracement_depth_ratio: float
    mean_body_ratio_to_impulse: float
    overlap_ratio: float
    tightness_ratio: float
    counter_pressure_ratio: float
    orderliness_score: float
    quality_label: str
    reasons: tuple[str, ...]
