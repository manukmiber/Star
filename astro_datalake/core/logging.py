"""Run logger: writes to logs/run-YYYYMMDD-HHMMSS.log plus console."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from .config import settings

_run_log_path: Path | None = None


def get_run_log_path() -> Path | None:
    return _run_log_path


def setup_logging(name: str = "astro_datalake", level: int = logging.INFO) -> logging.Logger:
    global _run_log_path

    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = settings.logs_dir / f"run-{timestamp}.log"
    _run_log_path = log_path

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False

    logger.info("Log file: %s", log_path)
    return logger
