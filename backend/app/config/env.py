"""Minimal `.env` loading for local development."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


DEFAULT_ENV_FILES: tuple[str, ...] = (".env", "secret.env")


def _iter_env_entries(path: str | Path) -> list[tuple[str, str]]:
    env_path = Path(path)
    if not env_path.exists():
        return []

    entries: list[tuple[str, str]] = []
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        entries.append((key, value))
    return entries


def _load_one_env_file(path: str | Path, *, override: bool = False) -> None:
    """Load `KEY=VALUE` pairs from one local env file if it exists."""

    for key, value in _iter_env_entries(path):
        if override or key not in os.environ:
            os.environ[key] = value


def load_env_files(
    paths: Iterable[str | Path] = DEFAULT_ENV_FILES,
    *,
    override: bool = False,
) -> None:
    """Load an ordered stack of env files.

    The default behavior is to load `.env` first, then `secret.env`. This keeps
    non-secret runtime settings separate from credentials while still allowing
    `secret.env` to override overlapping keys such as API credentials.
    """

    protected_keys = set(os.environ)
    loaded_keys: set[str] = set()
    for path in paths:
        for key, value in _iter_env_entries(path):
            should_override = override or key in loaded_keys
            if should_override or key not in protected_keys:
                os.environ[key] = value
                loaded_keys.add(key)


def load_env_file(path: str | Path | None = None, *, override: bool = False) -> None:
    """Backward-compatible env loader.

    When no path is provided, the runtime loads the default env stack:
    `.env` followed by `secret.env`. Passing an explicit path preserves the
    previous single-file behavior.
    """

    if path is None:
        load_env_files(override=override)
        return
    _load_one_env_file(path, override=override)
