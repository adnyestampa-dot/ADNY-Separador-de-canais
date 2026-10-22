from __future__ import annotations

import faulthandler
import logging
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from packages.core.models.app_settings import AppSettings
from packages.infra.logging.setup import setup_logging
from scf8.branding import APP_NAME
from scf8.ui.main_window import Scf8MainWindow
from scf8.ui.ss4_theme import apply_ss4_theme  # noqa: F401 — tema SS4 literal

logger = logging.getLogger(__name__)

# Settings próprios da Clean (não herdar geometria off-screen do beta).
_SETTINGS_APP = "ADNYSeparadorClean"


def _ensure_window_on_screen(window: Scf8MainWindow) -> None:
    """Se a geometria salva ficou fora do monitor, recentra a janela."""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()
    frame = window.frameGeometry()
    visible = False
    for s in QGuiApplication.screens():
        if s.availableGeometry().intersects(frame):
            visible = True
            break
    if visible and frame.width() >= 400 and frame.height() >= 300:
        return
    logger.warning("Geometria da janela inválida/fora da tela — recentrando.")
    window.resize(min(1400, available.width() - 80), min(900, available.height() - 80))
    geo = window.frameGeometry()
    geo.moveCenter(available.center())
    window.move(geo.topLeft())

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

    qsettings = QSettings(settings.organization, _SETTINGS_APP)
    geometry = qsettings.value("geometry")
    state = qsettings.value("windowState")
    if geometry:
        window.restoreGeometry(geometry)
    if state:
        window.restoreState(state)
    _ensure_window_on_screen(window)

    window.show()
    window.raise_()
    window.activateWindow()
    logger.info("Janela principal exibida: %s", window.windowTitle())

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
