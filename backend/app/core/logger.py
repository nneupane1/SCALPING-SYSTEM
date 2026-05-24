"""Structured logging helpers."""

from __future__ import annotations

import logging
from typing import Final

LOGGER_NAME: Final[str] = "scalping_system"


def configure_logging(debug: bool = False) -> logging.Logger:
    """Configure and return the project logger."""

    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    root.setLevel(logging.WARNING)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    return logger
