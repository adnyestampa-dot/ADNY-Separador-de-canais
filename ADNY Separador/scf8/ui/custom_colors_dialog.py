"""Janelas 'Custom Inks' e 'Custom Textiles' do SS4 (Edit > Inks... / Edit > Textiles...).

Lista (amostra + nome), '+' adiciona, X remove, undo/redo da janela, Close; o editor abre na
mesma janela: quadrado de cor + barra, Original/New, H S B · L a b · R G B (rádios) e C M Y K,
todos sincronizados, Cancel/Accept. Cada mudança aceita é entregue a ``on_change`` (persistência).
"""

from __future__ import annotations

from typing import Callable

import numpy as np
from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from scf8.core import color_models as cm
from scf8.ui.ss4_dialog_style import dialog_qss, help_button, pill_button, title_label

RGB = tuple[int, int, int]
ColorEntry = tuple[str, RGB]

# chave do campo → (grupo, rótulo, faixa)
FIELDS: dict[str, tuple[str, str, tuple[int, int]]] = {
    "H": ("hsb", "H:", (0, 360)), "S": ("hsb", "S:", (0, 100)), "Bv": ("hsb", "B:", (0, 100)),
    "L": ("lab", "L:", (0, 100)), "a": ("lab", "a:", (-128, 127)), "bl": ("lab", "b:", (-128, 127)),
    "R": ("rgb", "R:", (0, 255)), "G": ("rgb", "G:", (0, 255)), "Bc": ("rgb", "B:", (0, 255)),
    "C": ("cmyk", "C:", (0, 100)), "M": ("cmyk", "M:", (0, 100)), "Y": ("cmyk", "Y:", (0, 100)),
    "K": ("cmyk", "K:", (0, 100)),
}
GROUPS: dict[str, tuple[str, ...]] = {
    "hsb": ("H", "S", "Bv"), "lab": ("L", "a", "bl"), "rgb": ("R", "G", "Bc"), "cmyk": ("C", "M", "Y", "K"),
}
_RADIO_KEYS = ("H", "S", "Bv", "L", "a", "bl", "R", "G", "Bc")

# Textos padrão pt-BR (Edit > Inks... / Edit > Textiles...)
CUSTOM_INKS_TITLE = "Tintas personalizadas"
CUSTOM_INKS_NEW_NAME = "Tinta personalizada"
CUSTOM_INKS_EMPTY = "Clique no + para adicionar uma tinta personalizada"
CUSTOM_INKS_HELP = (
    "Clique em + para adicionar uma tinta, ▼ para editar e X para remover.\n"
    "As tintas aceitas ficam na biblioteca e entram na próxima separação."
)
CUSTOM_TEXTILES_TITLE = "Tecidos personalizados"
CUSTOM_TEXTILES_NEW_NAME = "Tecido personalizado"
CUSTOM_TEXTILES_EMPTY = "Clique no + para adicionar um tecido personalizado"
CUSTOM_TEXTILES_HELP = (
    "Clique em + para adicionar um tecido, ▼ para editar e X para remover.\n"
    "Escolha o tecido do documento em Exibir > Tecido… ou no botão Tecido…."
)

_EXTRA_QSS = """
QListWidget {{ background: #ffffff; color: #000000; font-size: 13px; }}
QLabel#{p}_empty {{ background: #ffffff; color: #000000; font-size: 13px; }}
QFrame#{p}_editor {{ background: #111111; border-radius: 4px; }}
QPushButton#{p}_add {{ color: #ffffff; background: #1e1e1e; border: 2px solid #1f9a2a; border-radius: 16px;
  min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; font-size: 20px; }}
QPushButton#{p}_undo, QPushButton#{p}_redo {{ color: #e6e6e6; background: #1e1e1e; border: 2px solid #4a4a4a;
  border-radius: 15px; min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; font-size: 16px; }}
QPushButton#{p}_undo:enabled, QPushButton#{p}_redo:enabled {{ border-color: #4a9be8; }}
QPushButton#{p}_remove {{ color: #e02a2a; background: transparent; border: 2px solid #e02a2a; border-radius: 13px;
  min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; font-weight: bold; }}
QPushButton#{p}_expand {{ color: #ffffff; background: transparent; border: none; font-size: 18px; }}
QLineEdit#{p}_name {{ background: #d0d4d4; color: #000000; border: 2px solid #8fc0b8; padding: 4px; }}
QRadioButton {{ color: #e6e6e6; }}
"""


def _swatch_icon(rgb: RGB) -> QIcon:
    pixmap = QPixmap(28, 18)
    pixmap.fill(QColor(*rgb))
    return QIcon(pixmap)


def _qimage(array: np.ndarray) -> QImage:
    data = np.ascontiguousarray(array)
    return QImage(data.data, data.shape[1], data.shape[0], data.strides[0], QImage.Format.Format_RGB888).copy()


class _PickerSquare(QWidget):
    """Quadrado de cor: os dois componentes não marcados no rádio."""

    picked = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(200, 200)
        self.mode, self.rgb = "R", (255, 255, 255)
        self._image: QImage | None = None

    def set_color(self, mode: str, rgb: RGB) -> None:
        self.mode, self.rgb = mode, rgb
        self._image = _qimage(cm.picker_square(mode, rgb, 128))
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        if self._image is not None:
            painter.drawImage(self.rect(), self._image)
        fx, fy, _ = cm.picker_marker(self.mode, self.rgb)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#000000"), 1.2))
        painter.drawEllipse(QPointF(fx * self.width(), fy * self.height()), 5, 5)
        painter.end()

    def _pick(self, event) -> None:
        pos = event.position()
        self.picked.emit(cm.picker_pick(self.mode, self.rgb, fx=pos.x() / self.width(), fy=pos.y() / self.height()))

    def mousePressEvent(self, event) -> None:
        self._pick(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event)


class _PickerBar(QWidget):
    """Barra vertical do componente marcado no rádio."""

    picked = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(22, 200)
        self.mode, self.rgb = "R", (255, 255, 255)
        self._image: QImage | None = None

    def set_color(self, mode: str, rgb: RGB) -> None:
        self.mode, self.rgb = mode, rgb
        self._image = _qimage(cm.picker_bar(mode, rgb, 128))
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        if self._image is not None:
            painter.drawImage(self.rect().adjusted(4, 0, -4, 0), self._image)
        _, _, fbar = cm.picker_marker(self.mode, self.rgb)
        y = fbar * self.height()
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(0, int(y), self.width(), int(y))
        painter.end()

    def _pick(self, event) -> None:
        self.picked.emit(cm.picker_pick(self.mode, self.rgb, fbar=event.position().y() / self.height()))

    def mousePressEvent(self, event) -> None:
        self._pick(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event)


class CustomColorsDialog(QDialog):
    """Modelo comum das janelas Custom Inks / Custom Textiles (prefixo ``ink`` / ``tex`` nos nomes)."""

    def __init__(
        self,
        parent,
        *,
        title: str,
        prefix: str,
        entries: list[ColorEntry],
        on_change: Callable[[list[ColorEntry]], None],
        new_name: str,
        empty_text: str,
        help_text: str,
    ) -> None:
        super().__init__(parent)
        self._p = prefix
        self._on_change = on_change
        self._new_name = new_name
        self._entries: list[ColorEntry] = [(n, tuple(rgb)) for n, rgb in entries]  # type: ignore[misc]
        self._history: list[list[ColorEntry]] = [list(self._entries)]
        self._pos = 0
        self._edit_row: int | None = None
        self._pending = False
        self._original: RGB = (255, 255, 255)
        self._rgb: RGB = (255, 255, 255)
        self._updating = False
        self.setObjectName(f"ss4_custom_{prefix}")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setStyleSheet(dialog_qss(f"ss4_custom_{prefix}") + _EXTRA_QSS.format(p=prefix))

        layout = QVBoxLayout(self)
        layout.addWidget(title_label(title))

        self.list = QListWidget()
        self.list.setObjectName(f"{prefix}_list")
        self.list.setIconSize(QSize(28, 18))
        self.list.currentRowChanged.connect(self._on_row_changed)
        self.empty = QLabel(empty_text)
        self.empty.setObjectName(f"{prefix}_empty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self._stack = QStackedWidget()
        self._stack.addWidget(self.list)
        self._stack.addWidget(self.empty)
        self._stack.setMinimumHeight(110)
        layout.addWidget(self._stack, stretch=1)

        layout.addWidget(self._build_strip())
        layout.addWidget(self._build_editor())

        footer = QHBoxLayout()
        footer.addWidget(help_button(self, title, help_text))
        self.add_btn = self._button(f"{prefix}_add", "+", "Adicionar")
        self.add_btn.clicked.connect(self.add)
        footer.addWidget(self.add_btn)
        footer.addStretch(1)
        self.undo_btn = self._button(f"{prefix}_undo", "\u21b6", "Desfazer")
        self.redo_btn = self._button(f"{prefix}_redo", "\u21b7", "Refazer")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)
        footer.addWidget(self.undo_btn)
        footer.addWidget(self.redo_btn)
        footer.addStretch(1)
        close = pill_button("Fechar", "red")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)

        self._rebuild()
        self._show_editor(False)
        self.resize(640, 360)

    # ------------------------------------------------------------ construção
    @staticmethod
    def _button(name: str, text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(name)
        button.setToolTip(tip)
        return button

    def _build_strip(self) -> QFrame:
        p = self._p
        self.strip = QFrame()
        self.strip.setObjectName(f"{p}_strip")
        row = QHBoxLayout(self.strip)
        row.setContentsMargins(8, 6, 8, 6)
        self.expand_btn = self._button(f"{p}_expand", "\u25bc", "Editar")
        self.expand_btn.clicked.connect(self.toggle_editor)
        row.addWidget(self.expand_btn)
        row.addStretch(1)
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName(f"{p}_name")
        self.name_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_edit.setMinimumWidth(240)
        row.addWidget(self.name_edit)
        row.addStretch(1)
        self.remove_btn = self._button(f"{p}_remove", "X", "Remover")
        self.remove_btn.clicked.connect(self.remove)
        row.addWidget(self.remove_btn)
        return self.strip

    def _build_editor(self) -> QFrame:
        p = self._p
        self.editor = QFrame()
        self.editor.setObjectName(f"{p}_editor")
        outer = QVBoxLayout(self.editor)
        body = QHBoxLayout()
        self.square = _PickerSquare()
        self.bar = _PickerBar()
        self.square.picked.connect(lambda rgb: self.set_rgb(rgb))
        self.bar.picked.connect(lambda rgb: self.set_rgb(rgb))
        body.addWidget(self.square)
        body.addWidget(self.bar)

        fields = QGridLayout()
        fields.setHorizontalSpacing(8)
        self.original_sw = QLabel()
        self.new_sw = QLabel()
        for sw in (self.original_sw, self.new_sw):
            sw.setFixedSize(32, 32)
        fields.addWidget(QLabel("Original"), 0, 0, 1, 2, Qt.AlignmentFlag.AlignRight)
        fields.addWidget(self.original_sw, 0, 2)
        fields.addWidget(self.new_sw, 0, 3)
        fields.addWidget(QLabel("Nova"), 0, 4)
        self.spins: dict[str, QSpinBox] = {}
        self.radios: dict[str, QRadioButton] = {}
        self._radio_group = QButtonGroup(self)
        layout_pos = {
            "H": (1, 0), "S": (2, 0), "Bv": (3, 0), "R": (5, 0), "G": (6, 0), "Bc": (7, 0),
            "L": (1, 3), "a": (2, 3), "bl": (3, 3), "C": (5, 3), "M": (6, 3), "Y": (7, 3), "K": (8, 3),
        }
        for key, (group, label, (lo, hi)) in FIELDS.items():
            r, c = layout_pos[key]
            if key in _RADIO_KEYS:
                radio = QRadioButton(label)
                radio.setObjectName(f"{p}_mode_{key}")
                self._radio_group.addButton(radio)
                radio.toggled.connect(lambda on: on and self._update_picker())
                self.radios[key] = radio
                fields.addWidget(radio, r, c)
            else:
                fields.addWidget(QLabel(label), r, c, Qt.AlignmentFlag.AlignRight)
            spin = QSpinBox()
            spin.setObjectName(f"{p}_{key}")
            spin.setRange(lo, hi)
            spin.valueChanged.connect(lambda _v, g=group: self._on_field(g))
            self.spins[key] = spin
            fields.addWidget(spin, r, c + 1)
        self.radios["R"].setChecked(True)
        body.addLayout(fields)
        outer.addLayout(body)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = pill_button("Cancelar", "red")
        cancel.clicked.connect(self.cancel_edit)
        self.accept_btn = pill_button("Aceitar", "green")
        self.accept_btn.clicked.connect(self.accept_edit)
        buttons.addWidget(cancel)
        buttons.addWidget(self.accept_btn)
        outer.addLayout(buttons)
        return self.editor

    # ------------------------------------------------------------ lista
    def entries(self) -> list[ColorEntry]:
        return list(self._entries)

    def _rows(self) -> list[ColorEntry]:
        rows = list(self._entries)
        if self._pending:
            rows.append((self.name_edit.text() or self._new_name, self._rgb))
        return rows

    def _rebuild(self, select: int | None = None) -> None:
        self._updating = True
        self.list.clear()
        for name, rgb in self._rows():
            item = QListWidgetItem(_swatch_icon(rgb), name)
            self.list.addItem(item)
        if select is not None and 0 <= select < self.list.count():
            self.list.setCurrentRow(select)
        self._updating = False
        self._stack.setCurrentWidget(self.list if self.list.count() else self.empty)
        self.undo_btn.setEnabled(self._pos > 0)
        self.redo_btn.setEnabled(self._pos < len(self._history) - 1)

    def _on_row_changed(self, row: int) -> None:
        if self._updating:
            return
        if self._pending and row != len(self._entries):
            self._pending = False
            self._rebuild(select=row if row < len(self._entries) else None)
        if 0 <= row < len(self._entries):
            self.open_editor(row)
        elif not self._pending:
            self._edit_row = None
            self._show_editor(False)

    def _unique_name(self, base: str) -> str:
        names = {n for n, _ in self._entries}
        name, n = base, 2
        while name in names:
            name, n = f"{base} {n}", n + 1
        return name

    # ------------------------------------------------------------ editor
    def _show_editor(self, expanded: bool) -> None:
        self.strip.setVisible(self._edit_row is not None or self._pending)
        self.editor.setVisible(expanded)
        self.expand_btn.setText("\u25b2" if expanded else "\u25bc")

    def open_editor(self, row: int) -> None:
        name, rgb = self._entries[row]
        self._edit_row = row
        self._original = tuple(rgb)  # type: ignore[assignment]
        self.name_edit.setText(name)
        self.set_rgb(tuple(rgb))
        self._show_editor(True)

    def toggle_editor(self) -> None:
        if self._edit_row is None and not self._pending:
            row = self.list.currentRow()
            if 0 <= row < len(self._entries):
                self.open_editor(row)
            return
        self._show_editor(not self.editor.isVisible())

    def add(self) -> None:
        """'+': tinta nova (branca) no fim da lista, com o editor aberto."""
        if not self._pending:
            self._pending = True
            self._edit_row = len(self._entries)
            self._original = (255, 255, 255)
            self.name_edit.setText(self._unique_name(self._new_name))
            self.set_rgb((255, 255, 255))
        self._rebuild(select=len(self._entries))
        self._show_editor(True)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def accept_edit(self) -> None:
        if self._edit_row is None:
            return
        name = self.name_edit.text().strip() or self._unique_name(self._new_name)
        entries = list(self._entries)
        if self._pending:
            entries.append((name, self._rgb))
            row = len(entries) - 1
        else:
            row = self._edit_row
            entries[row] = (name, self._rgb)
        self._pending = False
        self._commit(entries, select=row)
        self._edit_row = row
        self._original = self._rgb
        self._update_swatches()
        self._show_editor(False)

    def cancel_edit(self) -> None:
        if self._pending:
            self._pending = False
            self._edit_row = None
            self._rebuild()
            self._show_editor(False)
            return
        if self._edit_row is not None:
            self.open_editor(self._edit_row)
        self._show_editor(False)

    def remove(self) -> None:
        row = self.list.currentRow()
        if self._pending and row in (-1, len(self._entries)):
            self.cancel_edit()
            return
        if not 0 <= row < len(self._entries):
            return
        entries = [e for i, e in enumerate(self._entries) if i != row]
        self._pending = False
        self._edit_row = None
        self._commit(entries)
        self._show_editor(False)

    # ------------------------------------------------------------ undo / redo
    def _commit(self, entries: list[ColorEntry], select: int | None = None) -> None:
        self._entries = list(entries)
        del self._history[self._pos + 1:]
        self._history.append(list(self._entries))
        self._pos = len(self._history) - 1
        self._on_change(list(self._entries))
        self._rebuild(select=select)

    def _jump(self, pos: int) -> None:
        self._pos = pos
        self._entries = list(self._history[pos])
        self._pending = False
        self._edit_row = None
        self._on_change(list(self._entries))
        self._rebuild()
        self._show_editor(False)

    def undo(self) -> None:
        if self._pos > 0:
            self._jump(self._pos - 1)

    def redo(self) -> None:
        if self._pos < len(self._history) - 1:
            self._jump(self._pos + 1)

    # ------------------------------------------------------------ campos sincronizados
    def rgb(self) -> RGB:
        return self._rgb

    def _mode(self) -> str:
        return next((k for k, r in self.radios.items() if r.isChecked()), "R")

    def _on_field(self, group: str) -> None:
        if self._updating:
            return
        v = {k: self.spins[k].value() for k in GROUPS[group]}
        if group == "rgb":
            rgb = (v["R"], v["G"], v["Bc"])
        elif group == "hsb":
            rgb = cm.hsb_to_rgb(v["H"], v["S"], v["Bv"])
        elif group == "lab":
            rgb = cm.lab_to_rgb(v["L"], v["a"], v["bl"])
        else:
            rgb = cm.cmyk_to_rgb(v["C"], v["M"], v["Y"], v["K"])
        self.set_rgb(rgb, source=group)

    def set_rgb(self, rgb, source: str | None = None) -> None:
        """Cor nova do editor: atualiza todos os campos (menos o grupo editado), as amostras e o quadrado."""
        self._rgb = tuple(int(c) for c in rgb)  # type: ignore[assignment]
        values: dict[str, float] = {}
        if source != "rgb":
            values.update(zip(GROUPS["rgb"], self._rgb))
        if source != "hsb":
            values.update(zip(GROUPS["hsb"], cm.rgb_to_hsb(self._rgb)))
        if source != "lab":
            values.update(zip(GROUPS["lab"], cm.rgb_to_lab(self._rgb)))
        if source != "cmyk":
            values.update(zip(GROUPS["cmyk"], cm.rgb_to_cmyk(self._rgb)))
        was = self._updating
        self._updating = True
        for key, value in values.items():
            self.spins[key].setValue(int(round(value)))
        self._updating = was
        self._update_swatches()
        self._update_picker()
        if self._pending and self.list.count() > len(self._entries):
            self.list.item(len(self._entries)).setIcon(_swatch_icon(self._rgb))

    def _update_swatches(self) -> None:
        for sw, rgb in ((self.original_sw, self._original), (self.new_sw, self._rgb)):
            sw.setStyleSheet(f"background: rgb({rgb[0]}, {rgb[1]}, {rgb[2]}); border: 1px solid #666;")
        r, g, b = self._rgb
        self.strip.setStyleSheet(f"QFrame#{self._p}_strip {{ background: rgb({r}, {g}, {b}); }}")

    def _update_picker(self) -> None:
        if not hasattr(self, "square"):
            return
        mode = self._mode()
        self.square.set_color(mode, self._rgb)
        self.bar.set_color(mode, self._rgb)
