"""Structured logging helpers."""

from __future__ import annotations

import logging
from typing import Final

LOGGER_NAME: Final[str] = "scalping_system"


def configure_logging(debug: bool = False) -> logging.Logger:
    """Configure and return the project logger."""

    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return logging.getLogger(LOGGER_NAME)

