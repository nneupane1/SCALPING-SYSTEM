"""Configuration loading helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from .models import ConfigBundle, RiskConfig, StrategyConfig, SystemConfig

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when dependency is missing.
    yaml = None


def _load_yaml(path: Path) -> Mapping[str, Any]:
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to load configuration files. "
            "Install it with `pip install pyyaml`."
        )
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Config file must contain a mapping at the top level: {path}")
    return payload


def load_config_bundle(
    system_path: str | Path,
    strategy_path: str | Path,
    risk_path: str | Path,
) -> ConfigBundle:
    """Load the three config files that define the runtime."""

    env_system_path = os.getenv("TRADING_SYSTEM_CONFIG")
    resolved_system_path = Path(env_system_path) if env_system_path else Path(system_path)
    system_payload = dict(_load_yaml(resolved_system_path))
    strategy_payload = _load_yaml(Path(strategy_path))
    risk_payload = _load_yaml(Path(risk_path))
    env_mode = os.getenv("TRADING_SYSTEM_MODE")
    if env_mode:
        app_payload = dict(system_payload.get("app", {}))
        app_payload["mode"] = env_mode
        system_payload["app"] = app_payload
    return ConfigBundle(
        system=SystemConfig.from_mapping(system_payload),
        strategy=StrategyConfig.from_mapping(strategy_payload),
        risk=RiskConfig.from_mapping(risk_payload),
    )
