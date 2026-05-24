"""Rich-powered in-place console dashboards for operator commands."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text


class CommandDashboard:
    """A stable in-place console dashboard with progress, metrics, and events."""

    def __init__(self, title: str, *, subtitle: str = "") -> None:
        self.title = title
        self.subtitle = subtitle
        self.console = Console()
        self.status = "initializing"
        self.phase = "starting"
        self.detail = ""
        self.metrics: dict[str, Any] = {}
        self.context: dict[str, Any] = {}
        self.events: deque[tuple[str, str]] = deque(maxlen=12)
        self.progress = Progress(
            TextColumn("[bold cyan]>[/]"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None, complete_style="green", finished_style="bright_green"),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            expand=True,
        )
        self.task_id = self.progress.add_task("waiting", total=None, completed=0)
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=6,
            transient=False,
        )

    def __enter__(self) -> "CommandDashboard":
        self._live.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            self.emit(
                "phase",
                status="failed",
                phase="aborted",
                detail=str(exc),
            )
            self.emit("event", level="error", message=str(exc))
        self._refresh()
        self._live.stop()

    def emit(self, event_type: str, **payload: Any) -> None:
        """Accept a generic structured event from runners or data services."""

        if event_type == "phase":
            self.status = str(payload.get("status", self.status))
            self.phase = str(payload.get("phase", self.phase))
            self.detail = str(payload.get("detail", self.detail))
        elif event_type == "progress":
            description = str(payload.get("description", self.phase))
            completed = payload.get("completed", 0)
            total = payload.get("total")
            self.progress.update(
                self.task_id,
                description=description,
                completed=completed,
                total=total,
            )
            if "status" in payload:
                self.status = str(payload["status"])
        elif event_type == "metrics":
            self.metrics.update(payload.get("metrics", {}))
        elif event_type == "context":
            self.context.update(payload.get("context", {}))
        elif event_type == "event":
            self._add_event(
                level=str(payload.get("level", "info")),
                message=str(payload.get("message", "")),
            )
        elif event_type == "complete":
            self.status = str(payload.get("status", "completed"))
            self.phase = str(payload.get("phase", "completed"))
            self.detail = str(payload.get("detail", self.detail))
            self.metrics.update(payload.get("metrics", {}))
            total = self.progress.tasks[self.task_id].total
            if total is not None:
                self.progress.update(self.task_id, completed=total)
        self._refresh()

    def _add_event(self, *, level: str, message: str) -> None:
        if message:
            self.events.appendleft((level.lower(), message))

    def _refresh(self) -> None:
        self._live.update(self._render(), refresh=True)

    def _render(self) -> Group:
        return Group(
            self._render_header(),
            Panel(self.progress, title="Progress", border_style="cyan"),
            self._render_tables(),
            self._render_events(),
        )

    def _render_header(self) -> Panel:
        text = Text()
        text.append(f"{self.phase}\n", style="bold white")
        if self.detail:
            text.append(self.detail, style="dim")
        title = f"[bold bright_white]{self.title}[/]"
        if self.subtitle:
            title = f"{title} [dim]- {self.subtitle}[/]"
        return Panel(
            text,
            title=title,
            subtitle=f"[bold]{self.status.upper()}[/]",
            border_style=self._status_color(),
        )

    def _render_tables(self) -> Table:
        grid = Table.grid(expand=True)
        grid.add_column(ratio=1)
        grid.add_column(ratio=1)
        grid.add_row(self._dict_panel("Metrics", self.metrics, "green"), self._dict_panel("Context", self.context, "magenta"))
        return grid

    def _dict_panel(self, title: str, mapping: dict[str, Any], border_style: str) -> Panel:
        table = Table(show_header=False, expand=True, box=None, pad_edge=False)
        table.add_column(style="bold cyan", ratio=1)
        table.add_column(justify="right", ratio=1)
        if mapping:
            for key, value in mapping.items():
                table.add_row(str(key), self._format_value(value))
        else:
            table.add_row("status", "[dim]waiting for data[/]")
        return Panel(table, title=title, border_style=border_style)

    def _render_events(self) -> Panel:
        table = Table(show_header=False, expand=True, box=None, pad_edge=False)
        table.add_column(width=10, style="bold")
        table.add_column(ratio=1)
        if self.events:
            for level, message in list(self.events):
                table.add_row(self._event_label(level), message)
        else:
            table.add_row("[dim]events[/]", "[dim]no notable events yet[/]")
        return Panel(table, title="Recent Events", border_style="yellow")

    def _event_label(self, level: str) -> str:
        palette = {
            "info": "[cyan]INFO[/]",
            "success": "[green]OK[/]",
            "warning": "[yellow]WARN[/]",
            "error": "[red]ERROR[/]",
        }
        return palette.get(level, f"[white]{level.upper()}[/]")

    def _status_color(self) -> str:
        mapping = {
            "initializing": "cyan",
            "running": "blue",
            "completed": "green",
            "cached": "green",
            "finalizing": "yellow",
            "failed": "red",
        }
        return mapping.get(self.status.lower(), "white")

    def _format_value(self, value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.2f}"
        if isinstance(value, int):
            return f"{value:,}"
        if isinstance(value, datetime):
            return value.isoformat(sep=" ", timespec="seconds")
        if value is None:
            return "-"
        return str(value)
