from __future__ import annotations

import faulthandler
import logging
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from packages.core.models.app_settings import AppSettings
from packages.infra.logging.setup import setup_logging
from scf8.branding import APP_NAME
from scf8.ui.main_window import Scf8MainWindow
from scf8.ui.ss4_theme import apply_ss4_theme  # noqa: F401 — tema SS4 literal

logger = logging.getLogger(__name__)

_FAULT_LOG = (
    Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    / "ADNY Separador"
    / "logs"
    / "faulthandler.log"
)
_fault_file = None


def _install_crash_guards() -> None:
    """pythonw engole traceback — grava em disco e mostra diálogo em vez de sumir."""
    global _fault_file
    try:
        _FAULT_LOG.parent.mkdir(parents=True, exist_ok=True)
        _fault_file = open(_FAULT_LOG, "a", encoding="utf-8")  # noqa: SIM115
        faulthandler.enable(file=_fault_file, all_threads=True)
    except OSError:
        faulthandler.enable(all_threads=True)

    def _hook(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        logger.error("Exceção não capturada:\n%s", text)
        try:
            crash = _FAULT_LOG.with_name("uncaught.log")
            crash.write_text(text, encoding="utf-8")
        except OSError:
            pass
        try:
            QMessageBox.critical(
                None,
                "Erro",
                "Ocorreu um erro e o app quase fechou.\n\n"
                + text[-1200:],
            )
        except Exception:
            pass

    sys.excepthook = _hook


def main() -> int:
    setup_logging()
    _install_crash_guards()
    logger.info("Iniciando %s (FAV8+)", APP_NAME)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parents[1] / "assets" / "adny_separador.ico")))
    app.setOrganizationName("ADNY Separador")
    # Evita quit se uma subjanela MDI sumir durante o refresh pós-separação
    app.setQuitOnLastWindowClosed(True)
    apply_ss4_theme(app)

    settings = AppSettings()
    window = Scf8MainWindow(settings)
    window.show()

    qsettings = QSettings(settings.organization, "ADNYSeparadorCompleta")
    geometry = qsettings.value("geometry")
    state = qsettings.value("windowState")
    if geometry:
        window.restoreGeometry(geometry)
    if state:
        window.restoreState(state)

    def _on_about_to_quit() -> None:
        # Evita abort do Qt 6.11 ao destruir widgets com jobs de preview ainda no pool.
        try:
            from PySide6.QtCore import QThreadPool

            channels = getattr(getattr(window, "presenter", None), "channels", None)
            if channels is not None and hasattr(channels, "_invalidate_preview_worker"):
                channels._invalidate_preview_worker()
            QThreadPool.globalInstance().waitForDone(2000)
        except Exception:
            logger.exception("Falha ao drenar thread pool no encerramento")

    app.aboutToQuit.connect(_on_about_to_quit)

    exit_code = app.exec()

    qsettings.setValue("geometry", window.saveGeometry())
    qsettings.setValue("windowState", window.saveState())
    logger.info("ADNY Separador encerrado com código %s", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
