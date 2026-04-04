"""Structured logging for DNB pipeline runs.

Configures both console output and a timestamped log file so that
pipeline runs can be reviewed after the fact.

Usage:
    from dnb.logging_config import setup_logging
    setup_logging()                          # console only
    setup_logging(log_dir="./logs")          # console + file
    setup_logging(log_dir="./logs", level=logging.DEBUG)
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logging(
    log_dir: str | Path | None = None,
    level: int = logging.INFO,
    name: str = "dnb",
) -> Path | None:
    """Configure DNB logging.

    Args:
        log_dir: If provided, write a timestamped log file here.
        level: Logging level (default INFO).
        name: Logger name prefix.

    Returns:
        Path to the log file, or None if console-only.
    """
    root = logging.getLogger(name)
    root.setLevel(level)

    # Remove existing handlers to avoid duplicates on repeated calls
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s  %(name)-30s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    # Also configure the root dnb.* loggers
    for sub in ["dnb.engine", "dnb.modules", "dnb.sources", "dnb.io"]:
        sub_logger = logging.getLogger(sub)
        sub_logger.setLevel(level)

    log_path = None
    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = log_dir / f"dnb_{timestamp}.log"

        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

        root.info("Log file: %s", log_path)

    return log_path