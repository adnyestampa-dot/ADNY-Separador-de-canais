from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from packages.core.models.channel_info import ChannelInfo
from packages.core.models.preview_display import PreviewDisplayMode
from packages.image.conversion import pil_to_qpixmap
from packages.image.separation_preview import mask_thumbnail

MIME_TYPE = "application/x-adny-channel-id"

_STYLE_NORMAL = ""
_STYLE_INSERT_ABOVE = (
    "QFrame#channelItem { border: 1px solid #3c3c3c; border-top: 3px solid #007acc; }"
)
_STYLE_INSERT_BELOW = (
    "QFrame#channelItem { border: 1px solid #3c3c3c; border-bottom: 3px solid #007acc; }"
)
_STYLE_MERGE = (
    "QFrame#channelItem { border: 2px solid #e6a817; background-color: #3a3428; }"
)


class ChannelItemWidget(QFrame):
    visibility_changed = Signal(str, bool)
    opacity_changed = Signal(str, float)
    reorder_requested = Signal(str, str, bool)
    merge_requested = Signal(str, str)
    color_change_requested = Signal(str)
    adjust_requested = Signal(str)
    isolate_requested = Signal(str, bool)

    def __init__(
        self,
        channel: ChannelInfo,
        parent: QWidget | None = None,
        *,
        preview_mode: PreviewDisplayMode = PreviewDisplayMode.PROOF,
    ) -> None:
        super().__init__(parent)
        self.channel_id = channel.id
        self.setObjectName("channelItem")
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._drag_start = None
        self._swatch_color = QColor(*channel.color_rgb)
        self._preview_mode = preview_mode
        self._channel: ChannelInfo | None = channel

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(4)

        grip = QLabel("≡")
        grip.setFixedWidth(12)
        grip.setToolTip("Arraste para reordenar; Shift+arraste para unir")
        grip.setStyleSheet("color: #858585; background: transparent;")
        top.addWidget(grip)

        self.eye_btn = QToolButton()
        self.eye_btn.setCheckable(True)
        self.eye_btn.setToolTip("Mostrar/ocultar")
        self.eye_btn.setText("👁")
        self.eye_btn.blockSignals(True)
        self.eye_btn.setChecked(channel.visible)
        self.eye_btn.blockSignals(False)
        self.eye_btn.toggled.connect(
            lambda checked: self.visibility_changed.emit(self.channel_id, checked)
        )
        top.addWidget(self.eye_btn)

        self.swatch_btn = QToolButton()
        self.swatch_btn.setFixedSize(20, 20)
        self.swatch_btn.setToolTip("Clique esquerdo: cor | Clique direito: ajustar")
        self.swatch_btn.clicked.connect(
            lambda: self.color_change_requested.emit(self.channel_id)
        )
        self.swatch_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.swatch_btn.customContextMenuRequested.connect(self._open_adjust_dialog)
        top.addWidget(self.swatch_btn)

        self.name_label = QLabel(channel.name)
        self.name_label.setStyleSheet(
            "font-weight: bold; font-size: 11px; color: #cccccc; background: transparent;"
        )
        self.name_label.setToolTip("Clique direito: ajustar saturação / choke")
        self.name_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.name_label.customContextMenuRequested.connect(self._open_adjust_dialog)
        top.addWidget(self.name_label, stretch=1)

        self.isolate_btn = QToolButton()
        self.isolate_btn.setText("K")
        self.isolate_btn.setCheckable(True)
        self.isolate_btn.setToolTip("Isolar/restaurar visualização da key")
        self.isolate_btn.setVisible(channel.role == "key")
        self.isolate_btn.toggled.connect(
            lambda checked: self.isolate_requested.emit(self.channel_id, checked)
        )
        top.addWidget(self.isolate_btn)

        self.adjust_btn = QToolButton()
        self.adjust_btn.setText("⚙")
        self.adjust_btn.setToolTip("Ajustar canal (saturation, tint, choke)")
        self.adjust_btn.clicked.connect(
            lambda: self.adjust_requested.emit(self.channel_id)
        )
        top.addWidget(self.adjust_btn)

        self.percent_label = QLabel("100%")
        self.percent_label.setFixedWidth(38)
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        top.addWidget(self.percent_label)

        layout.addLayout(top)

        self.preview_label = QLabel()
        self.preview_label.setFixedSize(52, 52)
        self.preview_label.setStyleSheet(
            "background: #1e1e1e; border: 1px solid #3c3c3c; border-radius: 2px;"
        )
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._update_preview_thumbnail(channel)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 200)
        self.slider.setToolTip("Opacidade / carga de tinta (0–200%)")
        self.slider.setTracking(True)
        self.slider.setPageStep(5)
        self.slider.blockSignals(True)
        self.slider.setValue(int(channel.opacity * 100))
        self.slider.blockSignals(False)
        self.percent_label.setText(f"{int(channel.opacity * 100)}%")
        self.slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self.slider)

        self.set_swatch_rgb(channel.color_rgb)

    def set_swatch_rgb(self, rgb: tuple[int, int, int]) -> None:
        r, g, b = rgb
        self._swatch_color = QColor(r, g, b)
        self.swatch_btn.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #555555; border-radius: 3px;"
        )

    def set_label(self, name: str) -> None:
        self.name_label.setText(name)

    def set_preview_display_mode(self, mode: PreviewDisplayMode) -> None:
        self._preview_mode = mode
        if self._channel is not None:
            self._update_preview_thumbnail(self._channel)

    def _update_preview_thumbnail(self, channel: ChannelInfo) -> None:
        mask = channel.mask
        if mask is None:
            self.preview_label.clear()
            return
        ink = None if self._preview_mode == PreviewDisplayMode.FILM else channel.color_rgb
        thumb = mask_thumbnail(mask, size=48, ink_rgb=ink)
        self.preview_label.setPixmap(pil_to_qpixmap(thumb))

    def refresh(self, channel: ChannelInfo) -> None:
        self._channel = channel
        self.set_swatch_rgb(channel.color_rgb)
        self.set_label(channel.name)
        self._update_preview_thumbnail(channel)
        self.eye_btn.blockSignals(True)
        self.eye_btn.setChecked(channel.visible)
        self.eye_btn.blockSignals(False)
        self.slider.blockSignals(True)
        self.slider.setValue(int(channel.opacity * 100))
        self.slider.blockSignals(False)
        self.percent_label.setText(f"{int(channel.opacity * 100)}%")
        self.isolate_btn.setVisible(channel.role == "key")

    def _open_adjust_dialog(self, *_args) -> None:
        self.adjust_requested.emit(self.channel_id)

    def _on_slider(self, value: int) -> None:
        self.percent_label.setText(f"{value}%")
        self.opacity_changed.emit(self.channel_id, value / 100.0)

    def _shift_merge(self) -> bool:
        mods = QApplication.keyboardModifiers()
        return bool(mods & Qt.KeyboardModifier.ShiftModifier)

    def _insert_before_at(self, pos_y: float) -> bool:
        return pos_y < self.height() / 2

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_start is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < 12:
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_TYPE, self.channel_id.encode("utf-8"))
        drag.setMimeData(mime)

        ghost = QPixmap(140, 28)
        ghost.fill(Qt.GlobalColor.transparent)
        painter = QPainter(ghost)
        painter.fillRect(0, 0, 28, 28, self._swatch_color)
        painter.setPen(QColor(230, 230, 230))
        suffix = " + unir" if self._shift_merge() else ""
        painter.drawText(34, 19, self.name_label.text()[:16] + suffix)
        painter.end()
        drag.setPixmap(ghost)
        drag.exec(Qt.DropAction.MoveAction)
        self._drag_start = None

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_TYPE):
            source = bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8")
            if source != self.channel_id:
                merge = self._shift_merge()
                if merge:
                    self.setStyleSheet(_STYLE_MERGE)
                elif self._insert_before_at(event.position().y()):
                    self.setStyleSheet(_STYLE_INSERT_ABOVE)
                else:
                    self.setStyleSheet(_STYLE_INSERT_BELOW)
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_TYPE):
            source = bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8")
            if source != self.channel_id:
                merge = self._shift_merge()
                if merge:
                    self.setStyleSheet(_STYLE_MERGE)
                elif self._insert_before_at(event.position().y()):
                    self.setStyleSheet(_STYLE_INSERT_ABOVE)
                else:
                    self.setStyleSheet(_STYLE_INSERT_BELOW)
                event.acceptProposedAction()
                return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.setStyleSheet(_STYLE_NORMAL)

    def dropEvent(self, event) -> None:
        self.setStyleSheet(_STYLE_NORMAL)
        if event.mimeData().hasFormat(MIME_TYPE):
            source = bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8")
            if source != self.channel_id:
                if self._shift_merge():
                    self.merge_requested.emit(source, self.channel_id)
                else:
                    insert_before = self._insert_before_at(event.position().y())
                    self.reorder_requested.emit(source, self.channel_id, insert_before)
                event.acceptProposedAction()


class TrashDropZone(QFrame):
    delete_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("trashZone")
        self.setAcceptDrops(True)
        self.setFixedHeight(44)
        self._set_idle_style()

        layout = QHBoxLayout(self)
        self._label = QLabel("🗑 Arraste um canal aqui para excluir")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

    def _set_idle_style(self) -> None:
        self.setStyleSheet(
            "#trashZone { border: 2px dashed #555555; border-radius: 4px; "
            "background: #2d2d2d; color: #858585; font-size: 11px; }"
        )

    def _set_hover_style(self) -> None:
        self.setStyleSheet(
            "#trashZone { border: 2px dashed #f14c4c; border-radius: 4px; "
            "background: #3a2222; color: #f48771; font-size: 11px; }"
        )

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_TYPE):
            self._set_hover_style()
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_idle_style()

    def dropEvent(self, event) -> None:
        self._set_idle_style()
        if event.mimeData().hasFormat(MIME_TYPE):
            channel_id = bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8")
            self.delete_requested.emit(channel_id)
            event.acceptProposedAction()
