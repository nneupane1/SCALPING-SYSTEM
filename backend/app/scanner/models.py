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
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PullbackAssessment:
    """Quality assessment for the pullback leg."""

    valid: bool
    retracement_depth_ratio: float
    mean_body_ratio_to_impulse: float
    orderliness_score: float
    reasons: tuple[str, ...]

