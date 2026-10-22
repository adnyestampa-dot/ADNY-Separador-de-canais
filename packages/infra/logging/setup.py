from __future__ import annotations

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


def get_log_dir() -> Path:
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    log_dir = Path(appdata) / "ADNY Separador" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure console + rotating file logging."""
    log_dir = get_log_dir()
    log_file = log_dir / f"adny_separador_{datetime.now():%Y%m%d}.log"

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)

    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    logger = logging.getLogger("adny_separador")
    logger.info("Logging iniciado: %s", log_file)
    return logger
