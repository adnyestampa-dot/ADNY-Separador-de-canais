from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from packages.infra.files.bundle import resource_path

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

_FALLBACK_QSS = """
QWidget { background-color: #1e1e1e; color: #d4d4d4; }
QMainWindow { background-color: #252526; }
QToolBar { background-color: #2d2d30; border: none; spacing: 4px; }
QPushButton { background-color: #3c3c3c; border: 1px solid #555; padding: 4px 10px; }
QPushButton:hover { background-color: #4a4a4a; }
"""

def apply_dark_pro_theme(app: QApplication) -> None:
    """Aplica o tema escuro profissional (estilo VS Code / Photoshop)."""
    app.setStyle("Fusion")
    qss_path = resource_path("apps", "desktop_qt", "themes", "dark_pro.qss")
    try:
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
    except OSError:
        logger.warning("Tema dark_pro.qss nao encontrado em %s; usando fallback.", qss_path)
        app.setStyleSheet(_FALLBACK_QSS)
