from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_QSS = Path(__file__).with_name("ss4_theme.qss")


def apply_ss4_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    try:
        app.setStyleSheet(_QSS.read_text(encoding="utf-8"))
    except OSError:
        logger.warning("ss4_theme.qss ausente; tema mínimo.")
        app.setStyleSheet("QMainWindow { background: #636363; }")
