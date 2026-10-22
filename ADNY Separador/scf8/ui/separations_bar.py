from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QDockWidget, QHBoxLayout, QMenu, QScrollArea, QWidget

from packages.core.models.channel_info import ChannelInfo
from packages.core.models.preview_display import PreviewDisplayMode
from scf8.catalog.ss4_actions import Ss4Action
from scf8.widgets.ss4_channel_tile import ProofPositiveTile, Ss4ChannelTile
from scf8.widgets.ss4_trash import Ss4TrashCan

_PROOF_THUMB_DEBOUNCE_MS = 250


class SeparationsBarDock(QDockWidget):
    """Barra inferior de separações do SS4: Proof Positive, uma miniatura por separação, lixeira."""

    channel_toggled = Signal(str, bool)
    channel_opacity_changed = Signal(str, float)
    channel_reorder_requested = Signal(list)
    channel_merge_requested = Signal(str, str)
    channel_color_change_requested = Signal(str)
    channel_delete_requested = Signal(str)
    channel_adjust_requested = Signal(str)
    channel_properties_requested = Signal(str)
    channel_isolate_requested = Signal(str, bool)
    preview_display_mode_changed = Signal(str)
    channel_print_toggled = Signal(str, bool)
    channel_selected = Signal(str)
    proof_selected = Signal()
    # Emitido sempre que a lista, os nomes ou a visibilidade das separações mudam na barra.
    channels_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("Separations", parent)
        self.setObjectName("dock_ss4_separations")
        self.setTitleBarWidget(QWidget())
        self._items: dict[str, Ss4ChannelTile] = {}
        self._selected_id: str | None = None
        self._preview_mode = PreviewDisplayMode.PROOF
        self._context_actions: list[Ss4Action] = []
        self._dispatch: Callable[[Ss4Action], None] | None = None
        self._pending_proof_image = None

        outer = QWidget()
        outer.setObjectName("ss4SeparationsBar")
        outer.setStyleSheet(
            "QWidget#ss4SeparationsBar, QWidget#ss4SeparationsStrip, QScrollArea"
            " { background: #141414; border: none; }"
            " QFrame#ss4ProofTile { background: transparent; }"
        )
        outer_layout = QHBoxLayout(outer)
        outer_layout.setContentsMargins(4, 2, 4, 2)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(124)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._strip = QWidget()
        self._strip.setObjectName("ss4SeparationsStrip")
        self._strip_layout = QHBoxLayout(self._strip)
        self._strip_layout.setContentsMargins(2, 2, 2, 2)
        self._strip_layout.setSpacing(8)
        self.proof_tile = ProofPositiveTile()
        self.proof_tile.clicked.connect(self._on_proof_clicked)
        self._strip_layout.addWidget(self.proof_tile)
        self._strip_layout.addStretch()
        scroll.setWidget(self._strip)
        outer_layout.addWidget(scroll, stretch=1)

        self.trash = Ss4TrashCan()
        self.trash.delete_requested.connect(self.channel_delete_requested)
        outer_layout.addWidget(self.trash, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.setWidget(outer)

        self._proof_timer = QTimer(self)
        self._proof_timer.setSingleShot(True)
        self._proof_timer.timeout.connect(self._flush_proof_image)

    # ------------------------------------------------------------ Proof Positive
    def set_proof_image(self, image) -> None:
        """Atualiza a miniatura do composite (com debounce: o preview ao vivo chega em rajadas)."""
        self._pending_proof_image = image
        if image is None:
            self._proof_timer.stop()
            self.proof_tile.set_image(None)
            return
        self._proof_timer.start(_PROOF_THUMB_DEBOUNCE_MS)

    def _flush_proof_image(self) -> None:
        self.proof_tile.set_image(self._pending_proof_image)

    def _on_proof_clicked(self) -> None:
        self.select_channel(None)
        self.proof_selected.emit()

    # ------------------------------------------------------------ menu de contexto
    def set_context_actions(
        self, actions: list[Ss4Action], dispatch: Callable[[Ss4Action], None]
    ) -> None:
        self._context_actions = list(actions)
        self._dispatch = dispatch

    def build_context_menu(self, channel_id: str) -> QMenu:
        menu = QMenu(self)
        menu.setProperty("channel_id", channel_id)
        for action in self._context_actions:
            if action.separator_before:
                menu.addSeparator()
            qt_action = menu.addAction(action.label)
            qt_action.setEnabled(action.enabled)
            if self._dispatch is not None:
                qt_action.triggered.connect(
                    lambda _checked=False, a=action: self._dispatch(a)  # type: ignore[misc]
                )
        return menu

    def _on_tile_context(self, channel_id: str, global_pos: QPoint) -> None:
        self.select_channel(channel_id)
        menu = self.build_context_menu(channel_id)
        self._exec_menu(menu, global_pos)
        menu.deleteLater()

    def _exec_menu(self, menu: QMenu, global_pos: QPoint) -> None:
        menu.exec(global_pos)

    # ------------------------------------------------------------ seleção
    def select_channel(self, channel_id: str | None) -> bool:
        """Torna a separação ativa (alvo de Delete/Duplicate/Adjust). None limpa a seleção."""
        if channel_id is not None and channel_id not in self._items:
            return False
        self._selected_id = channel_id
        for cid, item in self._items.items():
            item.set_selected(cid == channel_id)
        if channel_id is not None:
            self.channel_selected.emit(channel_id)
        return True

    def clear_channel_selection(self) -> None:
        self.select_channel(None)

    def selected_channel_id(self) -> str | None:
        if self._selected_id in self._items:
            return self._selected_id
        return None

    # ------------------------------------------------------------ separações
    def _connect_item(self, item: Ss4ChannelTile) -> None:
        item.visibility_changed.connect(self.channel_toggled)
        item.merge_requested.connect(self.channel_merge_requested)
        item.reorder_requested.connect(self._on_item_reorder)
        item.select_requested.connect(self.select_channel)
        item.context_menu_requested.connect(self._on_tile_context)
        item.adjust_requested.connect(self.channel_adjust_requested)
        item.properties_requested.connect(self.channel_properties_requested)

    def _on_item_reorder(self, source_id: str, target_id: str, insert_before: bool) -> None:
        ids = self.visual_channel_ids()
        if source_id not in ids or target_id not in ids or source_id == target_id:
            return
        ids.remove(source_id)
        idx = ids.index(target_id)
        if not insert_before:
            idx += 1
        ids.insert(idx, source_id)
        self._apply_visual_order(ids)
        self.channel_reorder_requested.emit(ids)

    def visual_channel_ids(self) -> list[str]:
        ids: list[str] = []
        for i in range(self._strip_layout.count()):
            w = self._strip_layout.itemAt(i).widget()
            if isinstance(w, Ss4ChannelTile):
                ids.append(w.channel_id)
        return ids

    def tile(self, channel_id: str) -> Ss4ChannelTile | None:
        return self._items.get(channel_id)

    def _apply_visual_order(self, ordered_ids: list[str]) -> None:
        stretch = self._strip_layout.takeAt(self._strip_layout.count() - 1)
        for channel_id in ordered_ids:
            item = self._items.get(channel_id)
            if item is not None:
                self._strip_layout.removeWidget(item)
        for channel_id in ordered_ids:
            item = self._items.get(channel_id)
            if item is not None:
                self._strip_layout.addWidget(item)
        if stretch:
            self._strip_layout.addItem(stretch)

    def set_preview_display_mode(self, mode: PreviewDisplayMode) -> None:
        self._preview_mode = mode
        for item in self._items.values():
            item.set_preview_display_mode(mode)

    def set_channels(
        self,
        channels: list[ChannelInfo],
        *,
        preview_mode: PreviewDisplayMode = PreviewDisplayMode.PROOF,
    ) -> None:
        self._preview_mode = preview_mode
        self._clear_channels()
        for ch in channels:
            tile = Ss4ChannelTile(ch, preview_mode=preview_mode)
            self._connect_item(tile)
            self._strip_layout.insertWidget(self._strip_layout.count() - 1, tile)
            self._items[ch.id] = tile
        if self._selected_id in self._items:
            self._items[self._selected_id].set_selected(True)
        else:
            self._selected_id = None
        if not channels:
            self.set_proof_image(None)
        self.channels_changed.emit()

    def remove_channel(self, channel_id: str) -> None:
        item = self._items.pop(channel_id, None)
        if channel_id == self._selected_id:
            self._selected_id = None
        if item is not None:
            self._strip_layout.removeWidget(item)
            item.deleteLater()
        self.channels_changed.emit()

    def update_channel(self, channel: ChannelInfo) -> None:
        item = self._items.get(channel.id)
        if item is not None:
            item.refresh(channel)
        self.channels_changed.emit()

    def set_channel_checked(self, channel_id: str, visible: bool) -> None:
        item = self._items.get(channel_id)
        if item is not None:
            item.visible_cb.blockSignals(True)
            item.visible_cb.setChecked(visible)
            item.visible_cb.blockSignals(False)
        self.channels_changed.emit()

    def _clear_channels(self) -> None:
        for item in self._items.values():
            item.setEnabled(False)
            item.hide()
            self._strip_layout.removeWidget(item)
            item.setParent(None)
            item.deleteLater()
        self._items.clear()
