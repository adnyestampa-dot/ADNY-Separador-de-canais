from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QProgressBar,
    QSpinBox,
    QStatusBar,
    QToolBar,
    QWidget,
)

logger = logging.getLogger(__name__)

from apps.desktop_qt.docks.params_dock import ParamsDock
from apps.desktop_qt.docks.textiles_dock import TextilesDock
from packages.core.models.app_settings import AppSettings
from scf8.catalog.ss4_actions import (
    MENU_TITLES,
    MENUBAR_ORDER,
    ActionKind,
    MenuId,
    Ss4Action,
    actions_for_menu,
)
from scf8.core.naming import separation_display_name
from scf8.presenters.scf8_presenter import Scf8Presenter
from scf8.ui.document_area import PROOF_VIEW, DocumentArea
from scf8.ui.separations_bar import SeparationsBarDock
from scf8.ui.ss4_icons import drag_pixmap, tool_icon
from scf8.ui.vuerite_widget import VueRiteWidget
from scf8.branding import APP_WINDOW_TITLE, APP_NAME, PROOF_VIEW_TITLE
from scf8.widgets.ink_checkbox import InkCheckBox

_MAIN_TOOLBAR_QSS = """
QToolBar#ss4_main { background: #1e1e1e; border: none; spacing: 4px; padding: 3px 6px; }
QToolBar#ss4_main QToolButton {
  color: #f0f0f0; background: #1e1e1e; border: 2px solid #3d8fe0; border-radius: 11px;
  padding: 2px 9px; margin: 1px;
}
QToolBar#ss4_main QToolButton:hover { background: #2b3a4a; }
QToolBar#ss4_main QToolButton:pressed { background: #23476e; }
QToolBar#ss4_main QToolButton#pill_green { border-color: #2fa84f; }
QToolBar#ss4_main QToolButton#pill_red { border-color: #e02a2a; }
QToolBar#ss4_main QLabel, QToolBar#ss4_main QCheckBox { color: #e6e6e6; }
"""

_TOOLS_QSS = """
QToolBar#ss4_tools { background: #1e1e1e; border: none; spacing: 2px; padding: 2px; }
QToolBar#ss4_tools QToolButton { background: transparent; border: 1px solid transparent; padding: 2px; }
QToolBar#ss4_tools QToolButton:checked { background: #1f3f5f; border-color: #3d8fe0; }
"""

_TOOL_OPTIONS_QSS = """
QToolBar#ss4_tool_options { background: #1e1e1e; border: none; spacing: 10px; padding: 3px 8px; min-height: 28px; }
QToolBar#ss4_tool_options QLabel { color: #e6e6e6; }
QToolBar#ss4_tool_options QSpinBox, QToolBar#ss4_tool_options QComboBox { background: #ffffff; color: #000000; }
"""

# Opções por ferramenta na barra 'Opções da ferramenta'.
TOOL_OPTIONS: dict[str, tuple[str, ...]] = {
    "saturate": ("diameter", "hardness", "range"),
    "desaturate": ("diameter", "hardness", "range"),
    "eraser": ("diameter", "hardness"),
    "lasso": ("feather",),
    "poly_lasso": ("feather",),
    "select": ("feather",),
}
# (chave interna, rótulo pt-BR) — a chave vai para o pincel (low/mid/high).
RANGE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("low", "Saturação baixa"),
    ("mid", "Saturação média"),
    ("high", "Saturação alta"),
)


class Scf8MainWindow(QMainWindow):
    """Janela principal — menus, barra Main, ferramentas e barra de separações."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        super().__init__()
        self._settings = settings or AppSettings()
        self.setWindowTitle(APP_WINDOW_TITLE)
        self.resize(1680, 960)

        self.presenter = Scf8Presenter(self)

        self.canvas = VueRiteWidget()
        self.documents = DocumentArea(self.canvas, self.presenter.render_document_view)
        self.documents.set_close_document_handler(self.presenter.close_document)
        self.setCentralWidget(self.documents)
        self._document_key: object = None

        self.channels_dock = SeparationsBarDock(self)
        self.params_dock = ParamsDock(self)
        self.params_dock.setWindowTitle("Opções da ferramenta")
        self.textiles_dock = TextilesDock(self)
        self.textiles_dock.setWindowTitle("Tecido")

        self.menus: dict[MenuId, QMenu] = {}
        self.qt_actions: dict[str, QAction] = {}
        self.toolbars: list[QToolBar] = []
        self._sep_lists: dict[str, tuple[QMenu, QAction, list[QAction]]] = {}
        self._sep_list_signature: tuple = ()
        self._new_window_menu: QMenu | None = None
        self._documents_anchor: tuple[QMenu, QAction] | None = None
        self._document_actions: list[QAction] = []
        self._document_signature: tuple = ()
        self._active_boxes: dict[str, InkCheckBox] = {}
        self._active_signature: tuple = ()
        self._sep_sync_timer = QTimer(self)
        self._sep_sync_timer.setSingleShot(True)
        self._sep_sync_timer.timeout.connect(self._sync_separations_ui_safe)

        self._build_menus()
        self._build_toolbars()
        self._build_docks()
        self._build_status_bar()
        self._connect_signals()
        self.set_toolbars_locked(self.presenter.toolbars_locked)
        self.sync_separations_ui()

    # ------------------------------------------------------------ ações do catálogo
    def _make_action(self, parent, action: Ss4Action) -> QAction:
        qt_action = QAction(action.label, parent)
        qt_action.setToolTip(action.description)
        qt_action.setObjectName(action.action_id)
        if action.shortcut:
            qt_action.setShortcut(QKeySequence(action.shortcut))
            if action.shortcut_display_only:
                # Conflito do SS4 real (Generate Brown × Close Document): o atalho aparece no
                # menu mas só vale com o menu em foco, para não ficar ambíguo.
                qt_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
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
                if action.kind == ActionKind.SEPARATION_LIST:
                    anchor = menu.addSeparator()
                    self._sep_lists[action.action_id] = (menu, anchor, [])
                elif action.kind == ActionKind.NEW_WINDOW_MENU:
                    self._new_window_menu = menu.addMenu(action.label)
                    self._new_window_menu.setObjectName(action.action_id)
                elif action.kind == ActionKind.DOCUMENT_WINDOWS:
                    anchor = QAction(self)
                    anchor.setVisible(False)
                    menu.addAction(anchor)
                    self._documents_anchor = (menu, anchor)
                else:
                    menu.addAction(self._make_action(menu, action))

    def _build_toolbars(self) -> None:
        main = QToolBar("Main")
        main.setObjectName("ss4_main")
        main.setStyleSheet(_MAIN_TOOLBAR_QSS)
        main.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, main)
        self.toolbars.append(main)
        for action in actions_for_menu("main_toolbar"):
            if action.separator_before:
                main.addSeparator()
            if action.kind == ActionKind.DRAG_ALL:
                self._add_drag_all(main, action)
            elif action.kind == ActionKind.ACTIVE_SEPARATIONS:
                main.addWidget(QLabel(action.label))
                self._active_container = QWidget()
                self._active_layout = QHBoxLayout(self._active_container)
                self._active_layout.setContentsMargins(4, 0, 4, 0)
                self._active_layout.setSpacing(5)
                main.addWidget(self._active_container)
            else:
                qt_action = self._make_action(main, action)
                main.addAction(qt_action)
                button = main.widgetForAction(qt_action)
                if button is not None and action.style:
                    button.setObjectName(f"pill_{action.style}")

        tools = QToolBar("Tools")
        tools.setObjectName("ss4_tools")
        tools.setStyleSheet(_TOOLS_QSS)
        tools.setOrientation(Qt.Orientation.Vertical)
        tools.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tools)
        self.toolbars.append(tools)
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        for action in actions_for_menu("tools"):
            qt_action = self._make_action(tools, action)
            icon = tool_icon(action.action_id)
            if icon is not None:
                qt_action.setIcon(icon)
            self._tool_group.addAction(qt_action)
            tools.addAction(qt_action)
        self._tool_group.triggered.connect(
            lambda _a: self.documents.set_navigation_tool(self.canvas.active_view.tool)
        )
        self._tool_group.triggered.connect(lambda _a: self.sync_tool_options())

        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self._build_tool_options()

    def _build_tool_options(self) -> None:
        """Barra 'Opções da ferramenta' (abaixo da Main): diâmetro, dureza, faixa e suavização."""
        bar = QToolBar("Opções da ferramenta")
        bar.setObjectName("ss4_tool_options")
        bar.setStyleSheet(_TOOL_OPTIONS_QSS)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        self.toolbars.append(bar)
        self.tool_options_bar = bar
        self._option_actions: dict[str, QAction] = {}

        self.opt_diameter = QSpinBox()
        self.opt_diameter.setObjectName("opt_diameter")
        self.opt_diameter.setRange(1, 500)
        self.opt_diameter.setSuffix("px")
        self.opt_diameter.setValue(32)
        self.opt_hardness = QSpinBox()
        self.opt_hardness.setObjectName("opt_hardness")
        self.opt_hardness.setRange(0, 100)
        self.opt_hardness.setSuffix("%")
        self.opt_hardness.setValue(50)
        self.opt_range = QComboBox()
        self.opt_range.setObjectName("opt_range")
        for key, label in RANGE_OPTIONS:
            self.opt_range.addItem(label, key)
        self.opt_feather = QSpinBox()
        self.opt_feather.setObjectName("opt_feather")
        self.opt_feather.setRange(0, 99)
        self.opt_feather.setValue(2)
        for key, label, widget in (
            ("diameter", "Diâmetro:", self.opt_diameter),
            ("hardness", "Dureza:", self.opt_hardness),
            ("range", "Faixa:", self.opt_range),
            ("feather", "Suavização:", self.opt_feather),
        ):
            group = QWidget()
            group.setObjectName(f"opt_group_{key}")
            row = QHBoxLayout(group)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(QLabel(label))
            row.addWidget(widget)
            self._option_actions[key] = bar.addWidget(group)

        self.canvas.set_brush_diameter(self.opt_diameter.value())
        self.canvas.set_feather(self.opt_feather.value())
        self.presenter.set_brush_hardness(self.opt_hardness.value())
        self.presenter.set_brush_range(str(self.opt_range.currentData() or "low"))
        self.opt_diameter.valueChanged.connect(self.canvas.set_brush_diameter)
        self.canvas.brush_diameter_changed.connect(self.opt_diameter.setValue)
        self.opt_hardness.valueChanged.connect(self.presenter.set_brush_hardness)
        self.opt_range.currentIndexChanged.connect(
            lambda _i: self.presenter.set_brush_range(str(self.opt_range.currentData() or "low"))
        )
        self.opt_feather.valueChanged.connect(self.canvas.set_feather)
        self.sync_tool_options()

    def sync_tool_options(self) -> None:
        """Mostra na barra só as opções da ferramenta ativa."""
        tool = getattr(self.canvas.active_view.tool, "value", str(self.canvas.active_view.tool))
        shown = TOOL_OPTIONS.get(tool, ())
        for key, qt_action in self._option_actions.items():
            qt_action.setVisible(key in shown)

    def _add_drag_all(self, toolbar: QToolBar, action: Ss4Action) -> None:
        icon = QLabel()
        icon.setPixmap(drag_pixmap(24))
        icon.setToolTip("Arrastar")
        toolbar.addWidget(icon)
        self.drag_all_cb = QCheckBox(action.label)
        self.drag_all_cb.setObjectName(action.action_id)
        self.drag_all_cb.setChecked(self.presenter.drag_all_windows)
        self.drag_all_cb.toggled.connect(self.presenter.set_drag_all_windows)
        toolbar.addWidget(self.drag_all_cb)

    def _build_docks(self) -> None:
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.channels_dock)
        self.channels_dock.set_context_actions(
            actions_for_menu("separation_context"), self.presenter.dispatch
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.textiles_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.params_dock)
        self.tabifyDockWidget(self.textiles_dock, self.params_dock)
        self.textiles_dock.hide()
        self.params_dock.hide()

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
        # Adia a reconstrução de menus: no mesmo slot do fim do job o Qt 6.11
        # crashava ao deleteLater de QActions (app fechava após a separação).
        d.channels_changed.connect(lambda: self._sep_sync_timer.start(0))
        d.channels_changed.connect(p.schedule_underbase_sync)
        self.canvas.result_pixel_probed.connect(self._on_pixel_probe)
        self.canvas.brush_pressed.connect(p.begin_brush_stroke)
        self.canvas.brush_moved.connect(p.continue_brush_stroke)
        self.canvas.brush_released.connect(p.end_brush_stroke)
        self.canvas.display_image_changed.connect(d.set_proof_image)
        self.canvas.display_image_changed.connect(self.documents.schedule_refresh)
        d.channels_changed.connect(self.documents.schedule_refresh)
        self.documents.windows_changed.connect(self._rebuild_document_entries)
        self.textiles_dock.preset_changed.connect(p.set_textile_preset)

    # ------------------------------------------------------------ sincronização
    def _sync_separations_ui_safe(self) -> None:
        try:
            self.sync_separations_ui()
        except Exception:
            logger.exception("Falha ao sincronizar UI das separações")

    def sync_separations_ui(self) -> None:
        """Reflete as separações do documento nos menus, na barra 'Main' e no título."""
        state = self.presenter.project_state
        channels = list(state.channels)
        self._sync_document_windows()
        # Após a separação: Original (esquerda) + Imagem gerada (direita).
        if channels and state.active_document is not None:
            self.documents.ensure_compare_windows()
        signature = tuple((ch.id, separation_display_name(ch.name)) for ch in channels)
        if signature != self._sep_list_signature:
            self._sep_list_signature = signature
            self._rebuild_separation_lists(channels)
            self._rebuild_new_window_menu(channels)
        for _menu, _anchor, items in self._sep_lists.values():
            for qt_action, ch in zip(items, channels):
                qt_action.blockSignals(True)
                qt_action.setChecked(ch.visible)
                qt_action.blockSignals(False)
        self._sync_active_separations(channels)
        self._rebuild_document_entries()
        self._set_checked("view.textile_color", state.show_textile_color)
        self._set_checked("win.lock_toolbars", self.presenter.toolbars_locked)

    def _set_checked(self, action_id: str, checked: bool) -> None:
        qt_action = self.qt_actions.get(action_id)
        if qt_action is not None and qt_action.isChecked() != checked:
            qt_action.blockSignals(True)
            qt_action.setChecked(checked)
            qt_action.blockSignals(False)

    def _rebuild_separation_lists(self, channels) -> None:
        for key, (menu, anchor, items) in self._sep_lists.items():
            doomed = list(items)
            for qt_action in doomed:
                menu.removeAction(qt_action)
                qt_action.setParent(None)
            # deleteLater no próximo tick — no mesmo evento do fim do job crashava o Qt 6.11
            if doomed:
                QTimer.singleShot(0, lambda acts=doomed: [a.deleteLater() for a in acts])
            new_items: list[QAction] = []
            for ch in channels:
                qt_action = QAction(separation_display_name(ch.name), menu)
                qt_action.setCheckable(True)
                qt_action.setChecked(ch.visible)
                qt_action.setObjectName(f"{key}:{ch.id}")
                qt_action.triggered.connect(
                    lambda checked=False, cid=ch.id: self.presenter.set_separation_visible(cid, checked)
                )
                menu.insertAction(anchor, qt_action)
                new_items.append(qt_action)
            self._sep_lists[key] = (menu, anchor, new_items)

    def _rebuild_new_window_menu(self, channels) -> None:
        menu = self._new_window_menu
        if menu is None:
            return
        doomed = list(menu.actions())
        for qt_action in doomed:
            menu.removeAction(qt_action)
            qt_action.setParent(None)
        if doomed:
            QTimer.singleShot(0, lambda acts=doomed: [a.deleteLater() for a in acts])
        menu.setEnabled(bool(channels))
        if not channels:
            return
        from scf8.ui.document_area import ORIGINAL_VIEW

        entries = [
            ("Imagem Original", ORIGINAL_VIEW),
            (PROOF_VIEW_TITLE, PROOF_VIEW),
        ]
        entries += [(separation_display_name(ch.name), ch.id) for ch in channels]
        for name, kind in entries:
            qt_action = menu.addAction(name)
            qt_action.triggered.connect(lambda _c=False, k=kind: self.presenter.open_in_new_window(k))

    def _sync_document_windows(self) -> None:
        """Janela principal com o título do documento; outro documento fecha as janelas extras."""
        doc = self.presenter.project_state.active_document
        key = doc.id if doc is not None else None
        if key != self._document_key:
            self._document_key = key
            self.documents.close_extra_windows()
        self.documents.set_document_title(self.presenter.document_title())

    def _rebuild_document_entries(self) -> None:
        """Fim do menu Window: uma entrada por janela de documento aberta (a ativa marcada)."""
        if self._documents_anchor is None:
            return
        menu, anchor = self._documents_anchor
        windows = self.documents.document_windows()
        current = self.documents.current_window()
        signature = tuple((id(w), w.windowTitle(), w is current) for w in windows)
        if signature == self._document_signature:
            return
        self._document_signature = signature
        for qt_action in self._document_actions:
            menu.removeAction(qt_action)
            qt_action.deleteLater()
        self._document_actions = []
        for window in windows:
            qt_action = QAction(window.windowTitle(), menu)
            qt_action.setCheckable(True)
            qt_action.setChecked(window is current)
            qt_action.triggered.connect(lambda _c=False, w=window: self.documents.activate(w))
            menu.insertAction(anchor, qt_action)
            self._document_actions.append(qt_action)

    def _sync_active_separations(self, channels) -> None:
        signature = tuple((ch.id, tuple(ch.color_rgb), ch.name) for ch in channels)
        if signature != self._active_signature:
            self._active_signature = signature
            for box in self._active_boxes.values():
                self._active_layout.removeWidget(box)
                box.deleteLater()
            self._active_boxes = {}
            for ch in channels:
                box = InkCheckBox(ch.id, ch.color_rgb, separation_display_name(ch.name))
                box.toggled.connect(
                    lambda checked, cid=ch.id: self.presenter.set_separation_active(cid, checked)
                )
                self._active_layout.addWidget(box)
                self._active_boxes[ch.id] = box
        for cid, box in self._active_boxes.items():
            active = self.presenter.is_separation_active(cid)
            if box.isChecked() != active:
                box.blockSignals(True)
                box.setChecked(active)
                box.blockSignals(False)
                box.update()

    def active_separation_boxes(self) -> dict[str, InkCheckBox]:
        return dict(self._active_boxes)

    def separation_list_actions(self, list_id: str) -> list[QAction]:
        entry = self._sep_lists.get(list_id)
        return list(entry[2]) if entry else []

    # ------------------------------------------------------------ janela
    def set_toolbars_locked(self, locked: bool) -> None:
        for toolbar in self.toolbars:
            toolbar.setMovable(not locked)
            toolbar.setFloatable(not locked)
        self._set_checked("win.lock_toolbars", locked)

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
        """Pergunta se salva (se houver trabalho) e drena o pool antes de destruir widgets."""
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
