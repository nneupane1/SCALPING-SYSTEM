"""Typed configuration models for the trading runtime.

The repository uses plain dataclasses rather than a heavy validation framework
at this stage so that the initial implementation stays dependency-light and
fully inspectable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


def _require(mapping: Mapping[str, Any], key: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing required config key: {key}")
    return mapping[key]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"Cannot coerce value to bool: {value!r}")


@dataclass(frozen=True)
class SessionWindow:
    """A time-of-day window during which the system is allowed to trade."""

    name: str
    start: str
    end: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SessionWindow":
        return cls(
            name=str(_require(payload, "name")),
            start=str(_require(payload, "start")),
            end=str(_require(payload, "end")),
        )


@dataclass(frozen=True)
class AppConfig:
    """Top-level runtime identity and behavior flags."""

    name: str
    mode: str
    debug: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "AppConfig":
        return cls(
            name=str(_require(payload, "name")),
            mode=str(_require(payload, "mode")).lower(),
            debug=_as_bool(payload.get("debug", False)),
        )


@dataclass(frozen=True)
class AccountConfig:
    """Account-level capital settings."""

    initial_equity: float
    base_currency: str = "EUR"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "AccountConfig":
        return cls(
            initial_equity=float(_require(payload, "initial_equity")),
            base_currency=str(payload.get("base_currency", "EUR")).upper(),
        )


@dataclass(frozen=True)
class MarketConfig:
    """Canonical market selection and timeframe hierarchy."""

    symbol: str
    base_timeframe: str
    execution_timeframe: str
    context_timeframes: tuple[str, ...] = ()
    supported_execution_timeframes: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "MarketConfig":
        context_timeframes = tuple(str(item) for item in payload.get("context_timeframes", []))
        execution_timeframe = str(_require(payload, "execution_timeframe"))
        supported = tuple(
            str(item)
            for item in payload.get("supported_execution_timeframes", [execution_timeframe])
        )
        return cls(
            symbol=str(_require(payload, "symbol")).upper(),
            base_timeframe=str(_require(payload, "base_timeframe")),
            execution_timeframe=execution_timeframe,
            context_timeframes=context_timeframes,
            supported_execution_timeframes=supported,
        )


@dataclass(frozen=True)
class SessionsConfig:
    """Session gating for time-of-day constraints."""

    enabled: bool
    timezone: str
    active_windows: tuple[SessionWindow, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SessionsConfig":
        windows = tuple(
            SessionWindow.from_mapping(window)
            for window in payload.get("active_windows", [])
        )
        return cls(
            enabled=_as_bool(payload.get("enabled", True)),
            timezone=str(_require(payload, "timezone")),
            active_windows=windows,
        )


@dataclass(frozen=True)
class StorageConfig:
    """Storage paths and in-memory cache limits."""

    root: Path
    cache_limit: int = 5000

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "StorageConfig":
        return cls(
            root=Path(str(_require(payload, "root"))),
            cache_limit=int(payload.get("cache_limit", 5000)),
        )


@dataclass(frozen=True)
class HistoryConfig:
    """Configured historical research window."""

    start_date: str = "2024-01-01"
    end_date: str = "2024-12-31"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "HistoryConfig":
        return cls(
            start_date=str(payload.get("start_date", "2024-01-01")),
            end_date=str(payload.get("end_date", "2024-12-31")),
        )


@dataclass(frozen=True)
class BinanceConfig:
    """Network and request policy for Binance REST market-data access."""

    base_url: str = "https://api.binance.com"
    klines_path: str = "/api/v3/klines"
    default_interval: str = "1m"
    historical_limit: int = 1000
    recent_limit: int = 500
    request_timeout_seconds: float = 15.0
    retry_attempts: int = 5
    retry_backoff_seconds: float = 1.5
    retry_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504)
    retry_logging_enabled: bool = True
    ssl_verify: bool = True
    ca_bundle_path: str | None = None
    throttle_seconds: float = 0.2
    closed_klines_only: bool = True

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "BinanceConfig":
        retry_codes = tuple(int(code) for code in payload.get("retry_status_codes", (429, 500, 502, 503, 504)))
        ca_bundle = payload.get("ca_bundle_path")
        return cls(
            base_url=str(payload.get("base_url", "https://api.binance.com")),
            klines_path=str(payload.get("klines_path", "/api/v3/klines")),
            default_interval=str(payload.get("default_interval", "1m")),
            historical_limit=int(payload.get("historical_limit", 1000)),
            recent_limit=int(payload.get("recent_limit", 500)),
            request_timeout_seconds=float(payload.get("request_timeout_seconds", 15.0)),
            retry_attempts=int(payload.get("retry_attempts", 5)),
            retry_backoff_seconds=float(payload.get("retry_backoff_seconds", 1.5)),
            retry_status_codes=retry_codes,
            retry_logging_enabled=_as_bool(payload.get("retry_logging_enabled", True)),
            ssl_verify=_as_bool(payload.get("ssl_verify", True)),
            ca_bundle_path=None if ca_bundle in (None, "") else str(ca_bundle),
            throttle_seconds=float(payload.get("throttle_seconds", 0.2)),
            closed_klines_only=_as_bool(payload.get("closed_klines_only", True)),
        )


@dataclass(frozen=True)
class DownloadHistoryConfig:
    """Checkpoint and partial-file settings for long historical downloads."""

    checkpoint_dir: str = "_checkpoints"
    partial_suffix: str = ".partial.csv"
    checkpoint_suffix: str = ".checkpoint.json"
    resume_enabled: bool = True
    status_every_batches: int = 10
    save_every_batches: int = 1
    cleanup_partial_on_complete: bool = True

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DownloadHistoryConfig":
        return cls(
            checkpoint_dir=str(payload.get("checkpoint_dir", "_checkpoints")),
            partial_suffix=str(payload.get("partial_suffix", ".partial.csv")),
            checkpoint_suffix=str(payload.get("checkpoint_suffix", ".checkpoint.json")),
            resume_enabled=_as_bool(payload.get("resume_enabled", True)),
            status_every_batches=int(payload.get("status_every_batches", 10)),
            save_every_batches=int(payload.get("save_every_batches", 1)),
            cleanup_partial_on_complete=_as_bool(payload.get("cleanup_partial_on_complete", True)),
        )


@dataclass(frozen=True)
class DownloadsConfig:
    """Aggregate download policy settings."""

    history: DownloadHistoryConfig = field(default_factory=DownloadHistoryConfig)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DownloadsConfig":
        return cls(
            history=DownloadHistoryConfig.from_mapping(payload.get("history", {})),
        )


@dataclass(frozen=True)
class ResampleConfig:
    """Policy for pandas-style resampling semantics."""

    closed: str = "left"
    label: str = "right"
    drop_incomplete: bool = True

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResampleConfig":
        return cls(
            closed=str(payload.get("closed", "left")),
            label=str(payload.get("label", "right")),
            drop_incomplete=_as_bool(payload.get("drop_incomplete", True)),
        )


@dataclass(frozen=True)
class RuntimeCheckpointConfig:
    """Checkpoint settings for long-running simulation workloads."""

    enabled: bool = True
    checkpoint_dir: str = "_checkpoints"
    checkpoint_suffix: str = ".checkpoint.json"
    save_every_steps: int = 100
    output_dir: str = "output"
    resume_enabled: bool = True

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RuntimeCheckpointConfig":
        return cls(
            enabled=_as_bool(payload.get("enabled", True)),
            checkpoint_dir=str(payload.get("checkpoint_dir", "_checkpoints")),
            checkpoint_suffix=str(payload.get("checkpoint_suffix", ".checkpoint.json")),
            save_every_steps=int(payload.get("save_every_steps", 100)),
            output_dir=str(payload.get("output_dir", "output")),
            resume_enabled=_as_bool(payload.get("resume_enabled", True)),
        )


@dataclass(frozen=True)
class TransportConfig:
    """Network-facing runtime settings."""

    websocket_broadcast_buffer: int = 1000

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TransportConfig":
        return cls(
            websocket_broadcast_buffer=int(payload.get("websocket_broadcast_buffer", 1000))
        )


@dataclass(frozen=True)
class SystemConfig:
    """Configuration that describes the runtime environment."""

    app: AppConfig
    account: AccountConfig
    market: MarketConfig
    sessions: SessionsConfig
    storage: StorageConfig
    history: HistoryConfig
    binance: BinanceConfig
    downloads: DownloadsConfig
    resample: ResampleConfig
    backtest: RuntimeCheckpointConfig
    replay: RuntimeCheckpointConfig
    transport: TransportConfig

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SystemConfig":
        return cls(
            app=AppConfig.from_mapping(_require(payload, "app")),
            account=AccountConfig.from_mapping(_require(payload, "account")),
            market=MarketConfig.from_mapping(_require(payload, "market")),
            sessions=SessionsConfig.from_mapping(_require(payload, "sessions")),
            storage=StorageConfig.from_mapping(_require(payload, "storage")),
            history=HistoryConfig.from_mapping(payload.get("history", {})),
            binance=BinanceConfig.from_mapping(payload.get("binance", {})),
            downloads=DownloadsConfig.from_mapping(payload.get("downloads", {})),
            resample=ResampleConfig.from_mapping(payload.get("resample", {})),
            backtest=RuntimeCheckpointConfig.from_mapping(payload.get("backtest", {})),
            replay=RuntimeCheckpointConfig.from_mapping(payload.get("replay", {})),
            transport=TransportConfig.from_mapping(_require(payload, "transport")),
        )


@dataclass(frozen=True)
class ScannerConfig:
    """Rules used to decide whether the market is interesting enough to trade."""

    min_impulse_body_ratio: float = 1.5
    min_volume_ratio: float = 1.2
    max_pullback_depth_ratio: float = 0.8
    max_pullback_body_ratio: float = 0.75
    min_pullback_bars: int = 1
    max_pullback_bars: int = 3
    compression_lookback: int = 5

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ScannerConfig":
        return cls(
            min_impulse_body_ratio=float(payload.get("min_impulse_body_ratio", 1.5)),
            min_volume_ratio=float(payload.get("min_volume_ratio", 1.2)),
            max_pullback_depth_ratio=float(payload.get("max_pullback_depth_ratio", 0.8)),
            max_pullback_body_ratio=float(payload.get("max_pullback_body_ratio", 0.75)),
            min_pullback_bars=int(payload.get("min_pullback_bars", 1)),
            max_pullback_bars=int(payload.get("max_pullback_bars", 3)),
            compression_lookback=int(payload.get("compression_lookback", 5)),
        )


@dataclass(frozen=True)
class StrategyTriggerConfig:
    """Trigger-quality requirements for the entry candle."""

    require_breakout_close: bool = True
    min_close_position: float = 0.7
    min_body_ratio: float = 1.2
    stop_buffer_ratio: float = 0.05

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "StrategyTriggerConfig":
        return cls(
            require_breakout_close=_as_bool(payload.get("require_breakout_close", True)),
            min_close_position=float(payload.get("min_close_position", 0.7)),
            min_body_ratio=float(payload.get("min_body_ratio", 1.2)),
            stop_buffer_ratio=float(payload.get("stop_buffer_ratio", 0.05)),
        )


@dataclass(frozen=True)
class StrategyFilterConfig:
    """Optional indicator gates.

    These remain disabled in the current code path because the first pass does
    not yet build EMA or VWAP features. They are carried in config so the system
    shape stays consistent as those features are added later.
    """

    require_vwap_alignment: bool = False
    require_ema_alignment: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "StrategyFilterConfig":
        return cls(
            require_vwap_alignment=_as_bool(payload.get("require_vwap_alignment", False)),
            require_ema_alignment=_as_bool(payload.get("require_ema_alignment", False)),
        )


@dataclass(frozen=True)
class TimeframeCadenceConfig:
    """Research expectations for how a timeframe profile tends to behave."""

    expected_trades_per_day_low: int = 0
    expected_trades_per_day_high: int = 0
    expected_holding_bars_low: int = 0
    expected_holding_bars_high: int = 0
    runner_emphasis: str = "balanced"
    operator_focus: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TimeframeCadenceConfig":
        return cls(
            expected_trades_per_day_low=int(payload.get("expected_trades_per_day_low", 0)),
            expected_trades_per_day_high=int(payload.get("expected_trades_per_day_high", 0)),
            expected_holding_bars_low=int(payload.get("expected_holding_bars_low", 0)),
            expected_holding_bars_high=int(payload.get("expected_holding_bars_high", 0)),
            runner_emphasis=str(payload.get("runner_emphasis", "balanced")),
            operator_focus=str(payload.get("operator_focus", "")),
        )


@dataclass(frozen=True)
class StrategyRuleConfig:
    """Top-level rules for the active strategy."""

    name: str = "pullback_scalp"
    allow_long: bool = True
    allow_short: bool = True
    trigger: StrategyTriggerConfig = field(default_factory=StrategyTriggerConfig)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "StrategyRuleConfig":
        return cls(
            name=str(payload.get("name", "pullback_scalp")),
            allow_long=_as_bool(payload.get("allow_long", True)),
            allow_short=_as_bool(payload.get("allow_short", True)),
            trigger=StrategyTriggerConfig.from_mapping(payload.get("trigger", {})),
        )


@dataclass(frozen=True)
class TimeframeProfileConfig:
    """A concrete expression of the strategy for one execution timeframe."""

    name: str
    execution_timeframe: str
    description: str
    scanner: ScannerConfig
    trigger: StrategyTriggerConfig
    cadence: TimeframeCadenceConfig = field(default_factory=TimeframeCadenceConfig)

    @classmethod
    def from_mapping(
        cls,
        *,
        name: str,
        payload: Mapping[str, Any],
        default_scanner: ScannerConfig,
        default_trigger: StrategyTriggerConfig,
    ) -> "TimeframeProfileConfig":
        scanner_payload = payload.get("scanner")
        trigger_payload = payload.get("trigger")
        return cls(
            name=name,
            execution_timeframe=str(payload.get("execution_timeframe", name)),
            description=str(payload.get("description", "")),
            scanner=(
                ScannerConfig.from_mapping(scanner_payload)
                if isinstance(scanner_payload, Mapping)
                else default_scanner
            ),
            trigger=(
                StrategyTriggerConfig.from_mapping(trigger_payload)
                if isinstance(trigger_payload, Mapping)
                else default_trigger
            ),
            cadence=TimeframeCadenceConfig.from_mapping(payload.get("cadence", {})),
        )


@dataclass(frozen=True)
class StrategyConfig:
    """Aggregate strategy configuration."""

    scanner: ScannerConfig
    strategy: StrategyRuleConfig
    filters: StrategyFilterConfig
    profiles: tuple[TimeframeProfileConfig, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "StrategyConfig":
        scanner = ScannerConfig.from_mapping(_require(payload, "scanner"))
        strategy = StrategyRuleConfig.from_mapping(_require(payload, "strategy"))
        profiles_payload = payload.get("profiles", {})
        profiles: tuple[TimeframeProfileConfig, ...] = ()
        if isinstance(profiles_payload, Mapping):
            profiles = tuple(
                TimeframeProfileConfig.from_mapping(
                    name=str(name),
                    payload=profile_payload,
                    default_scanner=scanner,
                    default_trigger=strategy.trigger,
                )
                for name, profile_payload in profiles_payload.items()
                if isinstance(profile_payload, Mapping)
            )
        return cls(
            scanner=scanner,
            strategy=strategy,
            filters=StrategyFilterConfig.from_mapping(payload.get("filters", {})),
            profiles=profiles,
        )

    def resolve_profile(self, execution_timeframe: str) -> TimeframeProfileConfig:
        """Return the active timeframe expression for the selected execution clock."""

        for profile in self.profiles:
            if profile.execution_timeframe == execution_timeframe:
                return profile
        return TimeframeProfileConfig(
            name=f"default-{execution_timeframe}",
            execution_timeframe=execution_timeframe,
            description="Fallback profile generated from the top-level strategy config.",
            scanner=self.scanner,
            trigger=self.strategy.trigger,
            cadence=TimeframeCadenceConfig(),
        )


@dataclass(frozen=True)
class RiskLimitsConfig:
    """Risk budget and trade-frequency constraints."""

    risk_per_trade: float = 0.005
    max_open_positions: int = 1
    max_daily_loss_r: float = 3.0
    max_consecutive_losses: int = 4
    min_stop_distance_ratio: float = 0.0005
    max_position_notional: float | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RiskLimitsConfig":
        max_notional = payload.get("max_position_notional")
        return cls(
            risk_per_trade=float(payload.get("risk_per_trade", 0.005)),
            max_open_positions=int(payload.get("max_open_positions", 1)),
            max_daily_loss_r=float(payload.get("max_daily_loss_r", 3.0)),
            max_consecutive_losses=int(payload.get("max_consecutive_losses", 4)),
            min_stop_distance_ratio=float(payload.get("min_stop_distance_ratio", 0.0005)),
            max_position_notional=None if max_notional is None else float(max_notional),
        )


@dataclass(frozen=True)
class ManagementConfig:
    """Post-entry management rules."""

    first_partial_at_r: float = 1.0
    first_partial_size: float = 0.5
    move_stop_to_breakeven_after_first_partial: bool = True
    trailing_mode: str = "previous_candle_structure"
    trailing_lookback_bars: int = 1

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ManagementConfig":
        return cls(
            first_partial_at_r=float(payload.get("first_partial_at_r", 1.0)),
            first_partial_size=float(payload.get("first_partial_size", 0.5)),
            move_stop_to_breakeven_after_first_partial=_as_bool(
                payload.get("move_stop_to_breakeven_after_first_partial", True)
            ),
            trailing_mode=str(payload.get("trailing_mode", "previous_candle_structure")),
            trailing_lookback_bars=int(payload.get("trailing_lookback_bars", 1)),
        )


@dataclass(frozen=True)
class ExecutionConfig:
    """Constraints for order submission."""

    allow_live_orders: bool = False
    max_slippage_bps: float = 5.0

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExecutionConfig":
        return cls(
            allow_live_orders=_as_bool(payload.get("allow_live_orders", False)),
            max_slippage_bps=float(payload.get("max_slippage_bps", 5.0)),
        )


@dataclass(frozen=True)
class RiskConfig:
    """Aggregate risk and execution configuration."""

    risk: RiskLimitsConfig
    management: ManagementConfig
    execution: ExecutionConfig

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RiskConfig":
        return cls(
            risk=RiskLimitsConfig.from_mapping(_require(payload, "risk")),
            management=ManagementConfig.from_mapping(_require(payload, "management")),
            execution=ExecutionConfig.from_mapping(_require(payload, "execution")),
        )


@dataclass(frozen=True)
class ConfigBundle:
    """Complete runtime configuration assembled from the three config files."""

    system: SystemConfig
    strategy: StrategyConfig
    risk: RiskConfig
