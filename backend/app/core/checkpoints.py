"""Checkpoint helpers with atomic JSON writes."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class JsonCheckpointStore:
    """Read and write JSON checkpoints with Windows-friendly replace retries."""

    path: Path

    def read(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError(f"Checkpoint payload must be a JSON object: {self.path}")
        return payload

    def write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)

        last_error: PermissionError | None = None
        for attempt in range(1, 9):
            try:
                temp_path.replace(self.path)
                return
            except PermissionError as exc:
                last_error = exc
                if attempt == 8:
                    break
                time.sleep(0.15 * attempt)
        raise PermissionError(
            "Unable to replace checkpoint file after multiple attempts: "
            f"{self.path}"
        ) from last_error

    def delete(self) -> None:
        if self.path.exists():
            self.path.unlink()
