"""CLI entry point for forensic market-data audits."""

from __future__ import annotations

import argparse

from backend.app.console import CommandDashboard
from backend.app.data import MarketDataAuditor
from backend.app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit finalized 1m history and saved derived timeframe outputs.")
    parser.add_argument("--symbol", default=None, help="Optional symbol override.")
    parser.add_argument("--start-date", default=None, help="Optional start date override.")
    parser.add_argument("--end-date", default=None, help="Optional end date override.")
    parser.add_argument(
        "--skip-derived",
        action="store_true",
        help="Audit only the canonical base timeframe file and skip saved derived-frame comparisons.",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional explicit JSON output path for the audit report.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if any audit error is detected.",
    )
    args = parser.parse_args()

    app = create_app()
    with CommandDashboard("Data Audit", subtitle="Forensic OHLCV integrity checks") as dashboard:
        auditor = MarketDataAuditor(app.config, progress_callback=dashboard.emit)
        report = auditor.audit_history(
            symbol=args.symbol,
            start_date=args.start_date,
            end_date=args.end_date,
            include_derived=not args.skip_derived,
        )
        report_path = auditor.write_report(report, output_path=args.json_out)
        dashboard.emit(
            "complete",
            status="completed" if report.ok else "finalizing",
            phase="data audit command finished",
            detail=str(report_path),
            metrics={
                "audited_timeframes": len(report.summaries),
                "errors": report.error_count,
                "warnings": report.warning_count,
                "result": "clean" if report.ok else "issues_found",
            },
        )
    if args.strict and not report.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
