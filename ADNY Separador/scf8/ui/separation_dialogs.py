from __future__ import annotations

import math

import cv2
import numpy as np
from PySide6.QtCore import QByteArray, QMimeData, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDrag, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from packages.core.models.channel_info import ChannelInfo
from scf8.core import separation_ops as ops
from scf8.core.naming import separation_display_name
from scf8.ui.preferences_dialog import DEFAULT_PRESS_SIZE, PRESS_SIZE_RANGE
from scf8.ui.ss4_dialog_style import dialog_qss, help_button, pill_button, title_label

SEPARATION_MIME = "application/x-scf8-separation"
NEUTRAL_RGB = (160, 160, 160)
_PREVIEW_SIZE = 260
_PREVIEW_MARGIN = 12
_RING = QColor("#4a9be8")

HELP_TEXT = (
    "Telas: quantidade de telas na mesa (padrão: Telas padrão na mesa, em Preferências).\n\n"
    "Arraste a amostra de uma separação para uma tela ou escolha a tela na lista. "
    "Separações na mesma tela são combinadas ao clicar em Aplicar. A base branca fica na tela 1.\n\n"
    "Os botões de rotação giram toda a mesa no sentido horário ou anti-horário."
)

_EXTRA_QSS = """
QPushButton#pf_rot_cw, QPushButton#pf_rot_ccw, QPushButton#pf_undo, QPushButton#pf_redo {
  color: #e6e6e6; background: #1e1e1e; border: 2px solid #4a9be8; border-radius: 15px;
  min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; font-size: 16px; }
QRadioButton { color: #e6e6e6; }
QLabel#pf_section { color: #e6e6e6; font-size: 14px; }
"""


def _float_mask(mask: np.ndarray) -> np.ndarray:
    values = np.asarray(mask, dtype=np.float32)
    if values.size and values.max() > 1.0:
        values = values / 255.0
    return np.clip(values, 0.0, 1.0)


def _small(mask: np.ndarray, limit: int) -> np.ndarray:
    m = _float_mask(mask)
    h, w = m.shape[:2]
    scale = min(1.0, limit / max(h, w, 1))
    if scale >= 1.0:
        return m
    return cv2.resize(m, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)


class _SeparationSwatch(QLabel):
    """Amostra da separação na paleta 'Separations': arrastar para uma tela do carrossel."""

    def __init__(self, channel: ChannelInfo, *, draggable: bool) -> None:
        super().__init__()
        self.channel_id = channel.id
        self._rgb = tuple(channel.color_rgb)
        self._draggable = draggable
        self._press: QPoint | None = None
        self.setObjectName(f"pf_swatch:{channel.id}")
        self.setFixedSize(26, 26)
        r, g, b = self._rgb
        self.setStyleSheet(f"background: rgb({r}, {g}, {b}); border: 1px solid #666;")
        self.setToolTip(separation_display_name(channel.name) + ("" if draggable else " (tela 1)"))
        if draggable:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not self._draggable or self._press is None:
            return
        if (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        mime = QMimeData()
        mime.setData(SEPARATION_MIME, QByteArray(self.channel_id.encode("utf-8")))
        pixmap = QPixmap(22, 22)
        pixmap.fill(QColor(*self._rgb))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(pixmap)
        drag.exec(Qt.DropAction.MoveAction)


class PressFitCarousel(QWidget):
    """Carrossel 'Screens' visto de cima: N telas numeradas em volta do anel, tela 1 embaixo."""

    dropped = Signal(str, int)

    def __init__(self, spin: QSpinBox) -> None:
        super().__init__()
        self.setObjectName("pf_carousel")
        self.setAcceptDrops(True)
        self.setMinimumSize(300, 300)
        self._spin = spin
        spin.setParent(self)
        self._screens = spin.value()
        self._fills: dict[int, list[tuple[int, int, int]]] = {}
        self._locked: set[int] = set()

    def set_state(self, screens: int, fills: dict[int, list[tuple[int, int, int]]], locked: set[int]) -> None:
        self._screens, self._fills, self._locked = int(screens), fills, set(locked)
        self.update()

    def screen_angle(self, screen_no: int) -> float:
        """Ângulo (graus, y para baixo) do centro da tela: 1 embaixo, crescendo no sentido anti-horário."""
        return 90.0 - (screen_no - 1) * 360.0 / max(self._screens, 1)

    def screen_center(self, screen_no: int) -> QPointF:
        size = min(self.width(), self.height())
        theta = math.radians(self.screen_angle(screen_no))
        r = size * 0.34
        return QPointF(self.width() / 2 + r * math.cos(theta), self.height() / 2 + r * math.sin(theta))

    def screen_at(self, pos: QPointF) -> int:
        dx, dy = pos.x() - self.width() / 2, pos.y() - self.height() / 2
        theta = math.degrees(math.atan2(dy, dx))
        step = 360.0 / max(self._screens, 1)
        return int(round((90.0 - theta) / step)) % self._screens + 1

    def resizeEvent(self, event) -> None:
        hint = self._spin.sizeHint()
        self._spin.setGeometry((self.width() - hint.width()) // 2, (self.height() - hint.height()) // 2,
                               hint.width(), hint.height())
        super().resizeEvent(event)

    def paintEvent(self, _event) -> None:
        size = min(self.width(), self.height())
        cx, cy = self.width() / 2, self.height() / 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#111111"))
        ring = size * 0.15
        painter.setPen(QPen(_RING, size * 0.035))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), ring, ring)
        n = max(self._screens, 1)
        pallet_w = min(size * 0.17, 2 * math.pi * size * 0.34 / n * 0.8)
        pallet_h = size * 0.27
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSizeF(max(7.0, pallet_w * 0.22))
        painter.setFont(font)
        for screen_no in range(1, n + 1):
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(self.screen_angle(screen_no) - 90.0)
            # braço do anel até a tela
            painter.setPen(QPen(_RING, size * 0.03))
            painter.drawLine(QPointF(0, ring), QPointF(0, size * 0.34 - pallet_h / 2))
            rect = QRectF(-pallet_w / 2, size * 0.34 - pallet_h / 2, pallet_w, pallet_h)
            colors = self._fills.get(screen_no, [])
            painter.setPen(QPen(QColor("#c8c8c8"), 3))
            if colors:
                stripe = rect.width() / len(colors)
                for i, rgb in enumerate(colors):
                    painter.fillRect(QRectF(rect.left() + i * stripe, rect.top(), stripe + 0.5, rect.height()),
                                     QColor(*rgb))
                painter.setBrush(Qt.BrushStyle.NoBrush)
            else:
                painter.setBrush(QBrush(QColor("#9a9a9a"), Qt.BrushStyle.CrossPattern))
            painter.drawRoundedRect(rect, 4, 4)
            badge = QPointF(0, rect.top() + pallet_w * 0.32)
            radius = pallet_w * 0.27
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.setBrush(QColor("#000000"))
            painter.drawEllipse(badge, radius, radius)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(QRectF(badge.x() - radius, badge.y() - radius, 2 * radius, 2 * radius),
                             Qt.AlignmentFlag.AlignCenter, str(screen_no))
            painter.restore()
        painter.end()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(SEPARATION_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(SEPARATION_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        data = event.mimeData()
        if not data.hasFormat(SEPARATION_MIME):
            return
        channel_id = bytes(data.data(SEPARATION_MIME).data()).decode("utf-8")
        self.dropped.emit(channel_id, self.screen_at(event.position()))
        event.acceptProposedAction()


class PressFitDialog(QDialog):
    """Press Fit do manual SS4: carrossel 'Screens', paleta 'Separations', preview e Apply.

    Cada separação tem uma tela (1..N); as que dividem uma tela são fundidas ao aplicar
    (``assignment()`` + ``prefer()`` → ``separation_ops.press_fit_by_screens``).
    """

    def __init__(
        self,
        parent,
        channels: list[ChannelInfo],
        *,
        screens: int = DEFAULT_PRESS_SIZE,
        ground_rgb: tuple[int, int, int] = (20, 20, 20),
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ss4_press_fit")
        self.setWindowTitle("Encaixe na mesa")
        self.setModal(True)
        self.setStyleSheet(dialog_qss("ss4_press_fit") + _EXTRA_QSS)
        self._channels = list(channels)
        self._ground = tuple(int(c) for c in ground_rgb)
        self._locked = {ch.id for ch in self._channels if ops.is_underbase(ch)}
        self._small = {ch.id: _small(ch.mask, _PREVIEW_SIZE) for ch in self._channels if ch.mask is not None}
        self._coverage = {cid: float(m.mean()) for cid, m in self._small.items()}
        self._updating = False
        self._history: list[tuple[int, dict[str, int]]] = []
        self._pos = -1

        self._screens = QSpinBox()
        self._screens.setObjectName("pf_screens")
        self._screens.setRange(*PRESS_SIZE_RANGE)
        self._screens.setValue(int(min(max(screens, PRESS_SIZE_RANGE[0]), PRESS_SIZE_RANGE[1])))
        self._screens.setToolTip("Telas")
        self.carousel = PressFitCarousel(self._screens)
        self.carousel.dropped.connect(self.assign_to_screen)

        layout = QVBoxLayout(self)
        layout.addWidget(title_label("Encaixe na mesa"))
        body = QHBoxLayout()
        layout.addLayout(body, stretch=1)

        left = QVBoxLayout()
        left.addWidget(self._section("Telas"))
        left.addWidget(self.carousel, stretch=1)
        rotate = QHBoxLayout()
        rotate.addStretch(1)
        self.rot_cw = self._round_button("pf_rot_cw", "\u21bb", "Girar no sentido horário")
        self.rot_ccw = self._round_button("pf_rot_ccw", "\u21ba", "Girar no sentido anti-horário")
        self.rot_cw.clicked.connect(lambda: self.rotate(True))
        self.rot_ccw.clicked.connect(lambda: self.rotate(False))
        rotate.addWidget(self.rot_cw)
        rotate.addWidget(self.rot_ccw)
        rotate.addStretch(1)
        left.addLayout(rotate)
        left.addWidget(self._section("Separações"))
        left.addWidget(self._separation_rows(), stretch=1)
        body.addLayout(left, stretch=1)

        right = QVBoxLayout()
        right.addWidget(self._section("Visualização"))
        self.preview = QLabel()
        self.preview.setObjectName("pf_preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(_PREVIEW_SIZE + 2 * _PREVIEW_MARGIN + 30, _PREVIEW_SIZE + 2 * _PREVIEW_MARGIN)
        right.addWidget(self.preview, stretch=1)
        bg = QHBoxLayout()
        bg.addWidget(QLabel("Fundo:"))
        self.bg_neutral = QRadioButton("Neutro")
        self.bg_neutral.setObjectName("pf_bg_neutral")
        self.bg_textile = QRadioButton("Tecido")
        self.bg_textile.setObjectName("pf_bg_textile")
        self.bg_textile.setChecked(True)
        group = QButtonGroup(self)
        for radio in (self.bg_neutral, self.bg_textile):
            group.addButton(radio)
            radio.toggled.connect(lambda on: on and self._render_preview())
            bg.addWidget(radio)
        bg.addStretch(1)
        right.addLayout(bg)
        body.addLayout(right, stretch=1)

        footer = QHBoxLayout()
        footer.addWidget(help_button(self, "Encaixe na mesa", HELP_TEXT))
        self.undo_btn = self._round_button("pf_undo", "\u21b6", "Desfazer")
        self.redo_btn = self._round_button("pf_redo", "\u21b7", "Refazer")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)
        footer.addWidget(self.undo_btn)
        footer.addWidget(self.redo_btn)
        footer.addStretch(1)
        cancel = pill_button("Cancelar", "red")
        cancel.clicked.connect(self.reject)
        apply = pill_button("Aplicar", "green")
        apply.setDefault(True)
        apply.clicked.connect(self.accept)
        footer.addWidget(cancel)
        footer.addWidget(apply)
        layout.addLayout(footer)

        self._assignment: dict[str, int] = {}
        self._prefer: set[str] = set()
        self._screens.valueChanged.connect(self._on_screens_changed)
        self._replan(record=True)
        self.resize(760, 640)

    # ------------------------------------------------------------ construção
    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("pf_section")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    @staticmethod
    def _round_button(name: str, text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(name)
        button.setToolTip(tip)
        return button

    def _separation_rows(self) -> QScrollArea:
        rows = QWidget()
        grid = QGridLayout(rows)
        grid.setContentsMargins(4, 4, 4, 4)
        self.combos: dict[str, QComboBox] = {}
        for row, ch in enumerate(self._channels):
            locked = ch.id in self._locked
            grid.addWidget(_SeparationSwatch(ch, draggable=not locked), row, 0)
            grid.addWidget(QLabel(separation_display_name(ch.name)), row, 1)
            combo = QComboBox()
            combo.setObjectName(f"pf_assign:{ch.id}")
            combo.setToolTip("Tela")
            combo.setEnabled(not locked)
            combo.currentIndexChanged.connect(lambda _i, cid=ch.id: self._on_combo(cid))
            grid.addWidget(combo, row, 2)
            self.combos[ch.id] = combo
        grid.setColumnStretch(1, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: #1e1e1e; }")
        scroll.setWidget(rows)
        scroll.setMinimumHeight(min(220, 34 * max(1, len(self._channels)) + 8))
        return scroll

    # ------------------------------------------------------------ estado
    def screens(self) -> int:
        return int(self._screens.value())

    def assignment(self) -> dict[str, int]:
        return dict(self._assignment)

    def prefer(self) -> set[str]:
        """Separações que sobram no plano automático: ficam (com nome e cor) quando há fusão."""
        return set(self._prefer)

    def _replan(self, *, record: bool) -> None:
        n = self.screens()
        self._assignment = ops.press_fit_assignment(self._channels, n)
        merged = {source for source, _target in ops.press_fit_plan(self._channels, n)}
        self._prefer = {ch.id for ch in self._channels if ch.id not in merged}
        if record:
            self._record()
        self._refresh()

    def _on_screens_changed(self, _value: int) -> None:
        if not self._updating:
            self._replan(record=True)

    def _on_combo(self, channel_id: str) -> None:
        if self._updating or channel_id in self._locked:
            return
        text = self.combos[channel_id].currentText()
        if text.isdigit():
            self._set(channel_id, int(text))

    def _set(self, channel_id: str, screen_no: int) -> None:
        if channel_id in self._locked or channel_id not in self._assignment:
            return
        screen_no = max(1, min(self.screens(), int(screen_no)))
        if self._assignment[channel_id] == screen_no:
            return
        self._assignment[channel_id] = screen_no
        self._record()
        self._refresh()

    def assign_to_screen(self, channel_id: str, screen_no: int) -> None:
        """Soltar a amostra de uma separação numa tela do carrossel."""
        self._set(channel_id, screen_no)

    def rotate(self, clockwise: bool = True) -> None:
        self._assignment = ops.rotate_assignment(self._channels, self._assignment, self.screens(), clockwise)
        self._record()
        self._refresh()

    # ------------------------------------------------------------ undo / redo da janela
    def _record(self) -> None:
        del self._history[self._pos + 1:]
        self._history.append((self.screens(), dict(self._assignment)))
        self._pos = len(self._history) - 1
        self._update_undo_buttons()

    def _restore(self) -> None:
        n, assignment = self._history[self._pos]
        self._updating = True
        self._screens.setValue(n)
        self._updating = False
        merged = {source for source, _target in ops.press_fit_plan(self._channels, n)}
        self._prefer = {ch.id for ch in self._channels if ch.id not in merged}
        self._assignment = dict(assignment)
        self._update_undo_buttons()
        self._refresh()

    def undo(self) -> None:
        if self._pos > 0:
            self._pos -= 1
            self._restore()

    def redo(self) -> None:
        if self._pos < len(self._history) - 1:
            self._pos += 1
            self._restore()

    def _update_undo_buttons(self) -> None:
        if hasattr(self, "undo_btn"):
            self.undo_btn.setEnabled(self._pos > 0)
            self.redo_btn.setEnabled(self._pos < len(self._history) - 1)

    # ------------------------------------------------------------ desenho
    def _groups(self) -> dict[int, list[ChannelInfo]]:
        groups: dict[int, list[ChannelInfo]] = {}
        for ch in self._channels:
            groups.setdefault(self._assignment.get(ch.id, 1), []).append(ch)
        return groups

    def _keeper(self, members: list[ChannelInfo]) -> ChannelInfo:
        inks = [ch for ch in members if ch.id not in self._locked and ch.id in self._small] or members
        return max(inks, key=lambda ch: (ch.id in self._prefer, self._coverage.get(ch.id, 0.0)))

    def _refresh(self) -> None:
        n = self.screens()
        items = [str(i) for i in range(1, n + 1)]
        self._updating = True
        for cid, combo in self.combos.items():
            if [combo.itemText(i) for i in range(combo.count())] != items:
                combo.clear()
                combo.addItems(items)
            combo.setCurrentText(str(self._assignment.get(cid, 1)))
        self._updating = False
        fills = {s: [tuple(ch.color_rgb) for ch in members] for s, members in self._groups().items()}
        locked = {self._assignment.get(cid, 1) for cid in self._locked}
        self.carousel.set_state(n, fills, locked)
        self._render_preview()

    def background_rgb(self) -> tuple[int, int, int]:
        return NEUTRAL_RGB if self.bg_neutral.isChecked() else self._ground  # type: ignore[return-value]

    def _render_preview(self) -> None:
        if not hasattr(self, "preview"):
            return
        bg = np.asarray(self.background_rgb(), dtype=np.float32) / 255.0
        shape = next(iter(self._small.values())).shape[:2] if self._small else (_PREVIEW_SIZE, _PREVIEW_SIZE)
        out = np.empty((*shape, 3), dtype=np.float32)
        out[:] = bg
        swatches: list[tuple[int, int, int]] = []
        for screen_no, members in sorted(self._groups().items()):
            for ch in [m for m in members if m.id in self._locked]:
                if ch.id in self._small and self._small[ch.id].shape == shape:
                    m = self._small[ch.id][..., None]
                    out = out * (1.0 - m) + (np.asarray(ch.color_rgb, np.float32) / 255.0) * m
                swatches.append(tuple(ch.color_rgb))
            inks = [m for m in members if m.id not in self._locked and m.id in self._small]
            if not inks:
                continue
            keep = self._keeper(inks)
            merged = np.zeros(shape, dtype=np.float32)
            for ch in inks:
                if self._small[ch.id].shape == shape:
                    merged = ops.screen(merged, self._small[ch.id])
            m = merged[..., None]
            out = out * (1.0 - m) + (np.asarray(keep.color_rgb, np.float32) / 255.0) * m
            swatches.append(tuple(keep.color_rgb))
        art = (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        h, w = art.shape[:2]
        sw, gap, mg = 16, 6, _PREVIEW_MARGIN
        canvas = np.empty((h + 2 * mg, w + 2 * mg + sw + gap, 3), dtype=np.uint8)
        canvas[:] = (bg * 255.0 + 0.5).astype(np.uint8)
        canvas[mg:mg + h, mg + sw + gap:mg + sw + gap + w] = art
        for i, rgb in enumerate(swatches):
            y0 = mg + i * (sw + 3)
            if y0 + sw > canvas.shape[0]:
                break
            canvas[y0:y0 + sw, mg:mg + sw] = rgb
        canvas = np.ascontiguousarray(canvas)
        image = QImage(canvas.data, canvas.shape[1], canvas.shape[0], canvas.strides[0],
                       QImage.Format.Format_RGB888).copy()
        self.preview.setPixmap(QPixmap.fromImage(image))
