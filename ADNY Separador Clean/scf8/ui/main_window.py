"""Janela principal — versão Clean: só Arquivo (Abrir/Salvar) + barra de canais."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMenu,
    QProgressBar,
    QStatusBar,
    QToolBar,
)

logger = logging.getLogger(__name__)

from packages.core.models.app_settings import AppSettings
from scf8.branding import APP_WINDOW_TITLE, APP_NAME
from scf8.catalog.ss4_actions import (
    MENU_TITLES,
    MENUBAR_ORDER,
    MenuId,
    Ss4Action,
    actions_for_menu,
)
from scf8.presenters.scf8_presenter import Scf8Presenter
from scf8.ui.document_area import DocumentArea
from scf8.ui.separations_bar import SeparationsBarDock
from scf8.ui.vuerite_widget import VueRiteWidget


class Scf8MainWindow(QMainWindow):
    """UI enxuta: menu Arquivo (Abrir/Salvar), área do documento e barra de separações."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        super().__init__()
        self._settings = settings or AppSettings()
        self.setWindowTitle(APP_WINDOW_TITLE)
        self.resize(1400, 900)

        self.presenter = Scf8Presenter(self)

        self.canvas = VueRiteWidget()
        self.documents = DocumentArea(self.canvas, self.presenter.render_document_view)
        self.documents.set_close_document_handler(self.presenter.close_document)
        self.setCentralWidget(self.documents)
        self._document_key: object = None

        self.channels_dock = SeparationsBarDock(self)
        # Docks de tecido/ferramentas não existem nesta versão (API stub para o presenter).
        self.params_dock = None
        self.textiles_dock = None

        self.menus: dict[MenuId, QMenu] = {}
        self.qt_actions: dict[str, QAction] = {}
        self.toolbars: list[QToolBar] = []
        self._sep_lists: dict[str, tuple[QMenu, QAction, list[QAction]]] = {}
        self._sep_list_signature: tuple = ()
        self._new_window_menu: QMenu | None = None
        self._documents_anchor: tuple[QMenu, QAction] | None = None
        self._document_actions: list[QAction] = []
        self._document_signature: tuple = ()
        self._sep_sync_timer = QTimer(self)
        self._sep_sync_timer.setSingleShot(True)
        self._sep_sync_timer.timeout.connect(self._sync_separations_ui_safe)

        self._build_menus()
        self._build_docks()
        self._build_status_bar()
        self._connect_signals()
        self.sync_separations_ui()

    def _make_action(self, parent, action: Ss4Action) -> QAction:
        qt_action = QAction(action.label, parent)
        qt_action.setToolTip(action.description)
        qt_action.setObjectName(action.action_id)
        if action.shortcut:
            qt_action.setShortcut(QKeySequence(action.shortcut))
        if action.checkable:
            qt_action.setCheckable(True)
            qt_action.setChecked(action.checked)
        qt_action.setEnabled(action.enabled)
        qt_action.triggered.connect(lambda _checked=False, a=action: self.presenter.dispatch(a))
        self.qt_actions[action.action_id] = qt_action
        return qt_action

    def _build_menus(self) -> None:
        bar = self.menuBar()
        for menu_id in MENUBAR_ORDER:
            menu = bar.addMenu(MENU_TITLES[menu_id])
            menu.setObjectName(f"menu_{menu_id}")
            self.menus[menu_id] = menu
            for action in actions_for_menu(menu_id):
                if action.separator_before:
                    menu.addSeparator()
                menu.addAction(self._make_action(menu, action))

    def _build_docks(self) -> None:
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.channels_dock)
        self.channels_dock.set_context_actions(
            actions_for_menu("separation_context"), self.presenter.dispatch
        )

    def _build_status_bar(self) -> None:
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._xy_label = self._label("X: —  Y: —")
        self._file_label = self._label("Arquivo: —")
        self._resolution_label = self._label("Tamanho: —")
        self._dpi_label = self._label("DPI: —")
        self._density_label = self._label("Densidade: —")
        self._log_label = self._label("")
        self._progress = QProgressBar()
        self._progress.setMaximumWidth(120)
        self._progress.setRange(0, 100)
        self._status.addPermanentWidget(self._progress)
        for widget in (
            self._xy_label,
            self._file_label,
            self._resolution_label,
            self._dpi_label,
            self._density_label,
            self._log_label,
        ):
            self._status.addWidget(widget)

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("padding: 0 8px; color: #f0f0f0; background: transparent;")
        return label

    def _connect_signals(self) -> None:
        p = self.presenter
        d = self.channels_dock
        d.channel_toggled.connect(p.set_channel_visible)
        d.channel_opacity_changed.connect(p.set_channel_opacity)
        d.channel_reorder_requested.connect(p.reorder_channels)
        d.channel_merge_requested.connect(p.merge_channels)
        d.channel_color_change_requested.connect(p.change_channel_color)
        d.channel_delete_requested.connect(p.delete_channel)
        d.channel_adjust_requested.connect(p.adjust_separation)
        d.channel_properties_requested.connect(p.document_properties)
        d.channel_isolate_requested.connect(p.isolate_key_channel)
        d.channel_print_toggled.connect(p.set_channel_print_enabled)
        d.channels_changed.connect(lambda: self._sep_sync_timer.start(0))
        d.channels_changed.connect(p.schedule_underbase_sync)
        self.canvas.result_pixel_probed.connect(self._on_pixel_probe)
        self.canvas.display_image_changed.connect(d.set_proof_image)
        self.canvas.display_image_changed.connect(self.documents.schedule_refresh)
        d.channels_changed.connect(self.documents.schedule_refresh)
        self.documents.windows_changed.connect(self._rebuild_document_entries)

    def _sync_separations_ui_safe(self) -> None:
        try:
            self.sync_separations_ui()
        except Exception:
            logger.exception("Falha ao sincronizar UI das separações")

    def sync_separations_ui(self) -> None:
        state = self.presenter.project_state
        channels = list(state.channels)
        self._sync_document_windows()
        # Após a separação: Original (esquerda) + Imagem gerada (direita).
        if channels and state.active_document is not None:
            self.documents.ensure_compare_windows()
        self._rebuild_document_entries()

    def _sync_document_windows(self) -> None:
        doc = self.presenter.project_state.active_document
        key = doc.id if doc is not None else None
        if key != self._document_key:
            self._document_key = key
            self.documents.close_extra_windows()
        self.documents.set_document_title(self.presenter.document_title())

    def _rebuild_document_entries(self) -> None:
        return

    def separation_list_actions(self, list_id: str) -> list[QAction]:
        return []

    def set_toolbars_locked(self, locked: bool) -> None:
        return

    def sync_tool_options(self) -> None:
        return

    def _on_pixel_probe(self, x: int, y: int) -> None:
        self._xy_label.setText(f"X: {x}  Y: {y}")
        self.presenter.on_result_pixel_probe(x, y)

    def update_status_bar(self) -> None:
        doc = self.presenter.project_state.active_document
        if doc:
            self._file_label.setText(f"Arquivo: {doc.path or '—'}")
            self._resolution_label.setText(f"Tamanho: {doc.width}×{doc.height}")
            self._dpi_label.setText(f"DPI: {int(doc.dpi[0])}")
        else:
            self._file_label.setText("Arquivo: —")
            self._resolution_label.setText("Tamanho: —")
            self._dpi_label.setText("DPI: —")
        self._sync_document_windows()

    def set_progress(self, value: int, message: str = "") -> None:
        self._progress.setValue(value)
        if message:
            self.set_log_message(message)

    def set_separation_busy(self, busy: bool, message: str = "") -> None:
        if busy and message:
            self.set_log_message(message)

    def set_density_message(self, message: str) -> None:
        self._density_label.setText(f"Densidade: {message[:120]}")

    def set_log_message(self, message: str) -> None:
        self._log_label.setText(message[:100])

    def closeEvent(self, event) -> None:
        presenter = getattr(self, "presenter", None)
        if presenter is not None and hasattr(presenter, "prompt_save_before_quit"):
            if not presenter.prompt_save_before_quit():
                event.ignore()
                return
        try:
            channels = getattr(presenter, "channels", None) if presenter is not None else None
            if channels is not None and hasattr(channels, "_invalidate_preview_worker"):
                channels._invalidate_preview_worker()
            from PySide6.QtCore import QThreadPool

            QThreadPool.globalInstance().waitForDone(2000)
        except Exception:
            pass
        super().closeEvent(event)
