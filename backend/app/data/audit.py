"""Forensic audits for saved OHLCV history and derived timeframe outputs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.config.models import ConfigBundle, history_path_label

from .downloader import MarketDataDownloader
from .timeframe_builder import TimeframeBuilder

_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class AuditIssue:
    """One concrete data-integrity problem or warning."""

    level: str
    timeframe: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class TimeframeAuditSummary:
    """Quantitative integrity summary for one saved timeframe CSV."""

    timeframe: str
    path: str
    exists: bool
    raw_rows: int
    cleaned_rows: int
    first_timestamp: str | None
    last_timestamp: str | None
    duplicate_timestamps: int
    nan_cells: int
    non_monotonic_rows: int
    bad_step_count: int
    missing_intervals: int
    misaligned_timestamps: int
    requested_start_match: bool | None
    requested_end_match: bool | None
    recomputed_match: bool | None
    recomputed_expected_rows: int | None
    recomputed_missing_rows: int | None
    recomputed_extra_rows: int | None
    recomputed_value_mismatch_cells: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DataAuditReport:
    """Complete audit result over base history and optional derived outputs."""

    symbol: str
    start_date: str
    end_date: str
    base_timeframe: str
    generated_at: str
    ok: bool
    issue_count: int
    error_count: int
    warning_count: int
    summaries: tuple[TimeframeAuditSummary, ...]
    issues: tuple[AuditIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "base_timeframe": self.base_timeframe,
            "generated_at": self.generated_at,
            "ok": self.ok,
            "issue_count": self.issue_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "summaries": [summary.to_dict() for summary in self.summaries],
            "issues": [issue.to_dict() for issue in self.issues],
        }


class MarketDataAuditor:
    """Audit finalized market-history files before replay/backtest use."""

    def __init__(self, config: ConfigBundle, progress_callback=None) -> None:
        self.config = config
        self.progress_callback = progress_callback
        self.downloader = MarketDataDownloader(config=config, progress_callback=progress_callback)
        self.builder = TimeframeBuilder(config=config, progress_callback=progress_callback)

    def _emit(self, event_type: str, **payload: object) -> None:
        if callable(self.progress_callback):
            self.progress_callback(event_type, **payload)

    def _log(self, message: str, *, level: str = "info") -> None:
        if callable(self.progress_callback):
            self._emit("event", level=level, message=message)
            return
        print(message)

    def audit_history(
        self,
        *,
        symbol: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        include_derived: bool = True,
    ) -> DataAuditReport:
        symbol = (symbol or self.config.system.market.symbol).upper()
        start_date = start_date or self.config.system.history.start_date
        end_date = end_date or self.config.system.history.end_date

        self._emit(
            "phase",
            status="running",
            phase="auditing saved market data",
            detail=f"{symbol} | {start_date} -> {end_date}",
        )
        self._emit(
            "context",
            context={
                "symbol": symbol,
                "base_timeframe": self.config.system.market.base_timeframe,
                "execution_timeframe": self.config.system.market.execution_timeframe,
                "context_timeframes": ", ".join(self.config.system.market.context_timeframes) or "none",
                "range": f"{start_date} -> {end_date}",
            },
        )

        issues: list[AuditIssue] = []
        summaries: list[TimeframeAuditSummary] = []

        base_timeframe = self.config.system.market.base_timeframe
        base_path = self._history_path(
            symbol=symbol,
            timeframe=base_timeframe,
            start_date=start_date,
            end_date=end_date,
        )
        base_summary, base_clean = self._audit_saved_frame(
            path=base_path,
            timeframe=base_timeframe,
            requested_start=start_date,
            requested_end=end_date,
            compare_to=None,
        )
        summaries.append(base_summary)
        issues.extend(self._issues_for_summary(base_summary))

        if include_derived and base_clean is not None:
            expected_frames = self.builder.build_timeframes(base_clean)
            derived_timeframes = [
                timeframe
                for timeframe in (
                    self.config.system.market.execution_timeframe,
                    *self.config.system.market.context_timeframes,
                )
                if timeframe != base_timeframe
            ]
            total = len(derived_timeframes)
            for index, timeframe in enumerate(derived_timeframes, start=1):
                self._emit(
                    "progress",
                    description="Auditing derived timeframe outputs",
                    completed=index,
                    total=total,
                    status="running",
                )
                path = self._history_path(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_date=start_date,
                    end_date=end_date,
                )
                summary, _ = self._audit_saved_frame(
                    path=path,
                    timeframe=timeframe,
                    requested_start=None,
                    requested_end=None,
                    compare_to=expected_frames.get(timeframe),
                )
                summaries.append(summary)
                issues.extend(self._issues_for_summary(summary))

        error_count = sum(1 for issue in issues if issue.level == "error")
        warning_count = sum(1 for issue in issues if issue.level == "warning")
        ok = error_count == 0
        report = DataAuditReport(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            base_timeframe=base_timeframe,
            generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            ok=ok,
            issue_count=len(issues),
            error_count=error_count,
            warning_count=warning_count,
            summaries=tuple(summaries),
            issues=tuple(issues),
        )
        self._emit(
            "metrics",
            metrics={
                "audited_timeframes": len(summaries),
                "errors": error_count,
                "warnings": warning_count,
                "result": "clean" if ok else "issues_found",
            },
        )
        self._emit(
            "complete",
            status="completed" if ok else "finalizing",
            phase="data audit completed",
            detail=f"{symbol} | {start_date} -> {end_date}",
            metrics={
                "audited_timeframes": len(summaries),
                "errors": error_count,
                "warnings": warning_count,
                "result": "clean" if ok else "issues_found",
            },
        )
        return report

    def write_report(
        self,
        report: DataAuditReport,
        *,
        output_path: str | Path | None = None,
    ) -> Path:
        path = Path(output_path) if output_path is not None else self.default_report_path(
            symbol=report.symbol,
            start_date=report.start_date,
            end_date=report.end_date,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        self._log(f"Saved data audit report -> {path}", level="success")
        return path

    def default_report_path(self, *, symbol: str, start_date: str, end_date: str) -> Path:
        return (
            Path("audit")
            / "output"
            / f"{symbol}_data_audit_{history_path_label(start_date)}_to_{history_path_label(end_date)}.json"
        )

    def _history_path(self, *, symbol: str, timeframe: str, start_date: str, end_date: str) -> Path:
        folder = self.config.system.storage.root / symbol / timeframe
        normalized = (
            folder
            / (
                f"{symbol}_{timeframe}_{history_path_label(start_date)}"
                f"_to_{history_path_label(end_date)}.csv"
            )
        )
        if normalized.exists():
            return normalized
        legacy = folder / f"{symbol}_{timeframe}_{start_date}_to_{end_date}.csv"
        if legacy.exists():
            return legacy
        date_only_legacy = (
            folder
            / f"{symbol}_{timeframe}_{self._legacy_date_text(start_date)}_to_{self._legacy_date_text(end_date)}.csv"
        )
        if date_only_legacy.exists():
            return date_only_legacy
        return normalized

    def _legacy_date_text(self, value: str) -> str:
        timestamp = pd.Timestamp(value)
        if timestamp.hour == 0 and timestamp.minute == 0 and timestamp.second == 0:
            return timestamp.strftime("%Y-%m-%d")
        return value

    def _audit_saved_frame(
        self,
        *,
        path: Path,
        timeframe: str,
        requested_start: str | None,
        requested_end: str | None,
        compare_to: pd.DataFrame | None,
    ) -> tuple[TimeframeAuditSummary, pd.DataFrame | None]:
        if not path.exists():
            summary = TimeframeAuditSummary(
                timeframe=timeframe,
                path=str(path),
                exists=False,
                raw_rows=0,
                cleaned_rows=0,
                first_timestamp=None,
                last_timestamp=None,
                duplicate_timestamps=0,
                nan_cells=0,
                non_monotonic_rows=0,
                bad_step_count=0,
                missing_intervals=0,
                misaligned_timestamps=0,
                requested_start_match=None,
                requested_end_match=None,
                recomputed_match=None if compare_to is None else False,
                recomputed_expected_rows=None if compare_to is None else len(compare_to),
                recomputed_missing_rows=None,
                recomputed_extra_rows=None,
                recomputed_value_mismatch_cells=None,
            )
            return summary, None

        raw = self.downloader._read_ohlcv_csv(path)
        raw_rows = len(raw)
        duplicate_timestamps = int(raw["timestamp"].duplicated().sum())
        nan_cells = int(raw[list(_OHLCV_COLUMNS)].isna().sum().sum())
        non_monotonic_rows = self._count_non_monotonic_rows(raw["timestamp"])

        cleaned: pd.DataFrame | None = None
        try:
            indexed = raw.copy()
            indexed.set_index("timestamp", inplace=True)
            cleaned = self.downloader._validate_ohlcv(indexed)
        except Exception as exc:  # pragma: no cover - exercised as issue path
            self._log(f"{timeframe} validation failed: {exc}", level="error")

        bad_step_count = 0
        missing_intervals = 0
        misaligned_timestamps = 0
        first_timestamp = None
        last_timestamp = None
        requested_start_match = None
        requested_end_match = None
        recomputed_match = None
        recomputed_expected_rows = None
        recomputed_missing_rows = None
        recomputed_extra_rows = None
        recomputed_value_mismatch_cells = None

        if cleaned is not None and not cleaned.empty:
            first_timestamp = self._timestamp_text(cleaned.index[0])
            last_timestamp = self._timestamp_text(cleaned.index[-1])
            bad_step_count, missing_intervals = self._step_integrity(cleaned.index, timeframe=timeframe)
            misaligned_timestamps = self._misaligned_timestamp_count(cleaned.index, timeframe=timeframe)
            if requested_start is not None:
                requested_start_match = cleaned.index[0] == pd.Timestamp(requested_start)
            if requested_end is not None:
                expected_last = pd.Timestamp(requested_end) - self._expected_terminal_offset(timeframe)
                requested_end_match = cleaned.index[-1] == expected_last
            if compare_to is not None:
                (
                    recomputed_match,
                    recomputed_missing_rows,
                    recomputed_extra_rows,
                    recomputed_value_mismatch_cells,
                ) = self._compare_saved_to_recomputed(cleaned, compare_to)
                recomputed_expected_rows = len(compare_to)
        elif cleaned is not None:
            if requested_start is not None:
                requested_start_match = False
            if requested_end is not None:
                requested_end_match = False
            if compare_to is not None:
                recomputed_match = len(compare_to) == 0
                recomputed_expected_rows = len(compare_to)
                recomputed_missing_rows = len(compare_to)
                recomputed_extra_rows = 0
                recomputed_value_mismatch_cells = 0

        summary = TimeframeAuditSummary(
            timeframe=timeframe,
            path=str(path),
            exists=True,
            raw_rows=raw_rows,
            cleaned_rows=0 if cleaned is None else len(cleaned),
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
            duplicate_timestamps=duplicate_timestamps,
            nan_cells=nan_cells,
            non_monotonic_rows=non_monotonic_rows,
            bad_step_count=bad_step_count,
            missing_intervals=missing_intervals,
            misaligned_timestamps=misaligned_timestamps,
            requested_start_match=requested_start_match,
            requested_end_match=requested_end_match,
            recomputed_match=recomputed_match,
            recomputed_expected_rows=recomputed_expected_rows,
            recomputed_missing_rows=recomputed_missing_rows,
            recomputed_extra_rows=recomputed_extra_rows,
            recomputed_value_mismatch_cells=recomputed_value_mismatch_cells,
        )
        return summary, cleaned

    def _issues_for_summary(self, summary: TimeframeAuditSummary) -> list[AuditIssue]:
        issues: list[AuditIssue] = []
        timeframe = summary.timeframe
        if not summary.exists:
            issues.append(
                AuditIssue(
                    level="error",
                    timeframe=timeframe,
                    code="file_missing",
                    message=f"Expected saved {timeframe} history file is missing: {summary.path}",
                )
            )
            return issues
        if summary.duplicate_timestamps:
            issues.append(
                AuditIssue(
                    level="error",
                    timeframe=timeframe,
                    code="duplicate_timestamps",
                    message=f"{summary.duplicate_timestamps} duplicate timestamp row(s) detected in {timeframe}.",
                )
            )
        if summary.nan_cells:
            issues.append(
                AuditIssue(
                    level="error",
                    timeframe=timeframe,
                    code="nan_cells",
                    message=f"{summary.nan_cells} OHLCV NaN cell(s) detected in {timeframe}.",
                )
            )
        if summary.non_monotonic_rows:
            issues.append(
                AuditIssue(
                    level="warning",
                    timeframe=timeframe,
                    code="non_monotonic_input",
                    message=f"{summary.non_monotonic_rows} timestamp row(s) were out of order before cleaning in {timeframe}.",
                )
            )
        if summary.bad_step_count:
            base_timeframe = self.config.system.market.base_timeframe
            if timeframe == base_timeframe or summary.recomputed_match is not True:
                issues.append(
                    AuditIssue(
                        level="error",
                        timeframe=timeframe,
                        code="bad_step_count",
                        message=(
                            f"{summary.bad_step_count} broken interval step(s) detected in {timeframe}; "
                            f"{summary.missing_intervals} missing interval(s) implied."
                        ),
                    )
                )
        if summary.misaligned_timestamps:
            issues.append(
                AuditIssue(
                    level="error",
                    timeframe=timeframe,
                    code="misaligned_timestamps",
                    message=f"{summary.misaligned_timestamps} timestamp row(s) are off the expected {timeframe} boundary.",
                )
            )
        if summary.requested_start_match is False:
            issues.append(
                AuditIssue(
                    level="error",
                    timeframe=timeframe,
                    code="requested_start_mismatch",
                    message=f"The first saved {timeframe} timestamp does not match the requested start boundary.",
                )
            )
        if summary.requested_end_match is False:
            issues.append(
                AuditIssue(
                    level="error",
                    timeframe=timeframe,
                    code="requested_end_mismatch",
                    message=f"The last saved {timeframe} timestamp does not match the requested end boundary.",
                )
            )
        if summary.recomputed_match is False:
            issues.append(
                AuditIssue(
                    level="error",
                    timeframe=timeframe,
                    code="recomputed_mismatch",
                    message=(
                        f"Saved {timeframe} output diverges from canonical recomputation: "
                        f"missing_rows={summary.recomputed_missing_rows}, "
                        f"extra_rows={summary.recomputed_extra_rows}, "
                        f"value_mismatch_cells={summary.recomputed_value_mismatch_cells}."
                    ),
                )
            )
        return issues

    def _count_non_monotonic_rows(self, timestamps: pd.Series) -> int:
        diffs = timestamps.diff().dropna()
        return int((diffs <= pd.Timedelta(0)).sum())

    def _step_integrity(self, index: pd.Index, *, timeframe: str) -> tuple[int, int]:
        if len(index) < 2:
            return 0, 0
        expected_step = pd.Timedelta(self.builder._to_pandas_rule(timeframe))
        diffs = index.to_series().diff().dropna()
        bad_steps = diffs[diffs != expected_step]
        missing_intervals = 0
        for diff in bad_steps:
            if diff > expected_step:
                missing_intervals += max(0, int(diff / expected_step) - 1)
        return int(len(bad_steps)), int(missing_intervals)

    def _misaligned_timestamp_count(self, index: pd.Index, *, timeframe: str) -> int:
        rule = self.builder._to_pandas_rule(timeframe)
        floored = index.floor(rule)
        return int((floored != index).sum())

    def _expected_terminal_offset(self, timeframe: str) -> pd.Timedelta:
        if timeframe == self.config.system.market.base_timeframe:
            return MarketDataDownloader._interval_delta(timeframe)
        return pd.Timedelta(0)

    def _compare_saved_to_recomputed(
        self,
        saved: pd.DataFrame,
        expected: pd.DataFrame,
    ) -> tuple[bool, int, int, int]:
        saved_index = pd.Index(saved.index)
        expected_index = pd.Index(expected.index)
        missing_rows = int(len(expected_index.difference(saved_index)))
        extra_rows = int(len(saved_index.difference(expected_index)))
        common_index = expected_index.intersection(saved_index)
        mismatch_cells = 0
        if len(common_index):
            saved_common = saved.loc[common_index, list(_OHLCV_COLUMNS)].sort_index()
            expected_common = expected.loc[common_index, list(_OHLCV_COLUMNS)].sort_index()
            diff = (saved_common - expected_common).abs()
            mismatch_cells = int((diff > 1e-9).to_numpy().sum())
        return missing_rows == 0 and extra_rows == 0 and mismatch_cells == 0, missing_rows, extra_rows, mismatch_cells

    def _timestamp_text(self, timestamp: pd.Timestamp) -> str:
        return timestamp.isoformat(sep=" ", timespec="seconds")
