"""In-memory journal for state transitions."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.app.core.models import JournalEntry


class Journal:
    """Collect system events for later audit and UI display."""

    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []

    def record(self, stage: str, summary: str, **details: object) -> None:
        self._entries.append(
            JournalEntry(
                timestamp=datetime.now(timezone.utc),
                stage=stage,
                summary=summary,
                details=details,
            )
        )

    def entries(self) -> tuple[JournalEntry, ...]:
        return tuple(self._entries)

