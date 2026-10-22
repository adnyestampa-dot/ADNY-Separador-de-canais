from __future__ import annotations

import numpy as np
from PIL import Image
from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from shiboken6 import isValid

from apps.desktop_qt.widgets.channel_item import MIME_TYPE
from packages.core.models.channel_info import ChannelInfo
from packages.core.models.preview_display import PreviewDisplayMode
from packages.image.conversion import pil_to_qpixmap
from scf8.branding import PROOF_VIEW_TITLE
from scf8.core.naming import separation_display_name

THUMB_W, THUMB_H = 56, 72


def _fit_size(width: int, height: int) -> tuple[int, int]:
    scale = min(THUMB_W / max(1, width), THUMB_H / max(1, height))
    return max(1, int(width * scale)), max(1, int(height * scale))


def separation_thumbnail(mask: np.ndarray, ink_rgb: tuple[int, int, int] | None) -> Image.Image:
    """Miniatura da separação como no SS4: tinta sobre preto (Film View: preto sobre branco)."""
    values = mask.astype(np.float32, copy=False)
    if values.size and values.max() > 1.0:
        values = values / 255.0
    h, w = values.shape[:2]
    gray = Image.fromarray((np.clip(values, 0, 1) * 255).astype(np.uint8), mode="L")
    gray = gray.resize(_fit_size(w, h), Image.Resampling.BILINEAR)
    m = np.asarray(gray, dtype=np.float32)[..., None] / 255.0
    if ink_rgb is None:
        rgb = 255.0 * (1.0 - m) * np.ones(3, dtype=np.float32)
    else:
        rgb = m * np.array(ink_rgb, dtype=np.float32)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), mode="RGB")


def proof_thumbnail(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    return rgb.resize(_fit_size(rgb.width, rgb.height), Image.Resampling.BILINEAR)


def _thumb_label(border_rgb: tuple[int, int, int] = (200, 200, 200)) -> QLabel:
    label = QLabel()
    label.setFixedSize(THUMB_W + 4, THUMB_H + 4)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    r, g, b = border_rgb
    label.setStyleSheet(f"background: #000; border: 1px solid rgb({r}, {g}, {b});")
    return label


class ProofPositiveTile(QFrame):
    """Primeira miniatura da barra: o composite (Proof Positive)."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ss4ProofTile")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)
        self.title = QLabel(PROOF_VIEW_TITLE)
        self.title.setStyleSheet("color: #e6e6e6; font-size: 11px;")
        layout.addWidget(self.title)
        self.thumb = _thumb_label((230, 230, 230))
        layout.addWidget(self.thumb, alignment=Qt.AlignmentFlag.AlignHCenter)

    def set_image(self, image: Image.Image | None) -> None:
        if image is None:
            self.thumb.clear()
            return
        self.thumb.setPixmap(pil_to_qpixmap(proof_thumbnail(image)))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ColorSwatch(QLabel):
    """Caixa de cor abaixo da miniatura; clique direito abre Document Properties (SS4)."""

    properties_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sep_color_swatch")
        self.setFixedSize(THUMB_W, 8)
        self.setToolTip("Clique com o botão direito: propriedades do documento")

    def set_color(self, rgb: tuple[int, int, int]) -> None:
        r, g, b = rgb
        self.setStyleSheet(f"background: rgb({r}, {g}, {b}); border: 1px solid #777;")

    def contextMenuEvent(self, event) -> None:
        self.properties_requested.emit()
        event.accept()


class Ss4ChannelTile(QFrame):
    """Miniatura de uma separação na barra inferior (checkbox + nome + miniatura + caixa de cor)."""

    visibility_changed = Signal(str, bool)
    reorder_requested = Signal(str, str, bool)
    merge_requested = Signal(str, str)
    select_requested = Signal(str)
    context_menu_requested = Signal(str, QPoint)
    adjust_requested = Signal(str)
    properties_requested = Signal(str)

    _STYLE_NORMAL = (
        "QFrame#ss4ChannelTile { border: 1px solid transparent; border-radius: 2px;"
        " background: transparent; }"
    )
    _STYLE_SELECTED = (
        "QFrame#ss4ChannelTile { border: 1px solid #9ec9ff; border-radius: 2px;"
        " background: rgba(80, 140, 220, 60); }"
    )

    def __init__(
        self,
        channel: ChannelInfo,
        parent: QWidget | None = None,
        *,
        preview_mode: PreviewDisplayMode = PreviewDisplayMode.PROOF,
    ) -> None:
        super().__init__(parent)
        self.channel_id = channel.id
        self.setObjectName("ss4ChannelTile")
        self.setAcceptDrops(True)
        self._drag_start = None
        self._preview_mode = preview_mode
        self._channel = channel
        self._selected = False
        self.setStyleSheet(self._STYLE_NORMAL)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.visible_cb = QCheckBox()
        self.visible_cb.setChecked(channel.visible)
        self.visible_cb.setToolTip(f"Mostrar ou ocultar a separação na {PROOF_VIEW_TITLE.lower()}")
        self.visible_cb.toggled.connect(lambda v: self.visibility_changed.emit(self.channel_id, v))
        row.addWidget(self.visible_cb)
        self.name_label = QLabel()
        self.name_label.setStyleSheet("color: #e6e6e6; font-size: 11px;")
        row.addWidget(self.name_label, stretch=1)
        layout.addLayout(row)

        self.thumb = _thumb_label(channel.color_rgb)
        layout.addWidget(self.thumb, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.swatch = ColorSwatch()
        self.swatch.properties_requested.connect(self._on_swatch_properties)
        layout.addWidget(self.swatch, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.refresh(channel)

    def _on_swatch_properties(self) -> None:
        self.select_requested.emit(self.channel_id)
        self.properties_requested.emit(self.channel_id)

    @property
    def display_name(self) -> str:
        return separation_display_name(self._channel.name)

    def refresh(self, channel: ChannelInfo) -> None:
        self._channel = channel
        self.name_label.setText(separation_display_name(channel.name))
        self.setToolTip(channel.name)
        r, g, b = channel.color_rgb
        self.thumb.setStyleSheet(f"background: #000; border: 1px solid rgb({r}, {g}, {b});")
        self.swatch.set_color((r, g, b))
        if channel.mask is not None:
            ink = None if self._preview_mode == PreviewDisplayMode.FILM else channel.color_rgb
            self.thumb.setPixmap(pil_to_qpixmap(separation_thumbnail(channel.mask, ink)))
        self.visible_cb.blockSignals(True)
        self.visible_cb.setChecked(channel.visible)
        self.visible_cb.blockSignals(False)

    def set_preview_display_mode(self, mode: PreviewDisplayMode) -> None:
        self._preview_mode = mode
        if self._channel:
            self.refresh(self._channel)

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self.setStyleSheet(self._STYLE_SELECTED if selected else self._STYLE_NORMAL)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self.select_requested.emit(self.channel_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = None
            self.adjust_requested.emit(self.channel_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.select_requested.emit(self.channel_id)
        self.context_menu_requested.emit(self.channel_id, event.globalPos())
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not isValid(self):
            return
        if self._drag_start is None or event.buttons() != Qt.MouseButton.LeftButton:
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < 12:
            return
        self._drag_start = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_TYPE, self.channel_id.encode())
        drag.setMimeData(mime)
        try:
            drag.exec(Qt.DropAction.MoveAction)
        except RuntimeError:
            # Widget/Qt já em teardown — ignora o drag
            pass

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_TYPE):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        source_id = bytes(event.mimeData().data(MIME_TYPE)).decode()
        if source_id != self.channel_id:
            mods = event.modifiers()
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self.merge_requested.emit(source_id, self.channel_id)
            else:
                self.reorder_requested.emit(source_id, self.channel_id, True)
        event.acceptProposedAction()
