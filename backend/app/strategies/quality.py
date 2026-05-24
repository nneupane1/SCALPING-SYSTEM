"""Setup-quality scoring for risk scaling."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.config.models import StrategyFilterConfig
from backend.app.core.models import ScannerDecision

from .context import ContextAssessment
from .market_state import MarketStateAssessment
from .session_context import SessionAssessment


@dataclass(frozen=True)
class SetupQualityAssessment:
    """Risk and quality interpretation for one signal candidate."""

    score: float
    label: str
    risk_multiplier: float
    reasons: tuple[str, ...]


def assess_setup_quality(
    *,
    scanner_decision: ScannerDecision,
    trigger_body_ratio: float,
    trigger_close_position: float,
    entry_timing_score: float,
    context: ContextAssessment,
    market_state: MarketStateAssessment,
    session: SessionAssessment,
    config: StrategyFilterConfig.QualityConfig,
) -> SetupQualityAssessment:
    """Grade a setup without changing the underlying pattern definition."""

    impulse_component = max(
        0.0,
        min(
            1.0,
            float(scanner_decision.metrics.get("impulse_quality_score", scanner_decision.momentum_score)),
        ),
    )
    pullback_component = max(0.0, min(1.0, scanner_decision.pullback_score))
    trigger_component = max(
        0.0,
        min(1.0, ((min(2.0, trigger_body_ratio) / 2.0) + trigger_close_position) / 2.0),
    )
    pullback_label = str(scanner_decision.metrics.get("pullback_quality_label", "neutral"))
    pullback_label_component = {
        "clean": 1.0,
        "neutral": 0.72,
        "aggressive": 0.3,
    }.get(pullback_label, 0.65)
    context_component = {
        "aligned": 1.0,
        "neutral": 0.7,
        "conflicting": 0.42,
        "disabled": 0.7,
        "unavailable": 0.65,
    }.get(context.alignment, 0.65)
    market_component = {
        "trend": 1.0 if market_state.alignment == "aligned" else 0.45,
        "transition": 0.72,
        "compression": 0.68,
        "range": 0.56,
        "volatile_chop": 0.3,
        "disabled": 0.7,
        "unavailable": 0.65,
    }.get(market_state.state, 0.65)
    session_component = {
        "opening": 1.0,
        "core": 0.82,
        "closing": 0.62,
        "outside": 0.2,
        "disabled": 0.75,
    }.get(session.phase, 0.75)

    score = (
        impulse_component * 0.18
        + pullback_component * 0.18
        + pullback_label_component * 0.12
        + trigger_component * 0.18
        + max(0.0, min(1.0, entry_timing_score)) * 0.14
        + context_component * 0.1
        + market_component * 0.06
        + session_component * 0.04
    )
    score = max(0.0, min(1.0, score))
    if score >= config.strong_score:
        label = "elite"
    elif score >= config.marginal_score:
        label = "standard"
    elif score >= config.minimum_score:
        label = "marginal"
    else:
        label = "reject"

    if not config.enabled:
        risk_multiplier = 1.0
    else:
        span = max(1e-12, config.max_risk_multiplier - config.min_risk_multiplier)
        risk_multiplier = config.min_risk_multiplier + (score * span)
        risk_multiplier = max(config.min_risk_multiplier, min(config.max_risk_multiplier, risk_multiplier))

    reasons = (
        f"setup quality score {score:.2f}",
        f"quality tier: {label}",
        f"impulse tier: {scanner_decision.metrics.get('impulse_tier', 'unknown')}",
        f"pullback structure: {pullback_label}",
    )
    return SetupQualityAssessment(
        score=score,
        label=label,
        risk_multiplier=risk_multiplier,
        reasons=reasons,
    )
