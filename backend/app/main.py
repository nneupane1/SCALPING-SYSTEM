"""Backend application assembly entry point."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.api import RouteDefinition, WebSocketBroadcaster, default_routes
from backend.app.config import ConfigBundle, load_config_bundle, load_env_file
from backend.app.core.orchestrator import RuntimeContainer, build_runtime


@dataclass(frozen=True)
class ApplicationSurface:
    """Bundled application surface for API and runtime access."""

    config: ConfigBundle
    runtime: RuntimeContainer
    websocket: WebSocketBroadcaster
    routes: tuple[RouteDefinition, ...]


def create_app(
    *,
    system_path: str | Path = "backend/app/config/system.example.yaml",
    strategy_path: str | Path = "backend/app/config/strategy.example.yaml",
    risk_path: str | Path = "backend/app/config/risk.example.yaml",
) -> ApplicationSurface:
    """Build the current non-networked backend surface."""

    load_env_file()
    config = load_config_bundle(system_path, strategy_path, risk_path)
    runtime = build_runtime(config)
    websocket = WebSocketBroadcaster(
        buffer_size=config.system.transport.websocket_broadcast_buffer
    )
    return ApplicationSurface(
        config=config,
        runtime=runtime,
        websocket=websocket,
        routes=default_routes(),
    )
