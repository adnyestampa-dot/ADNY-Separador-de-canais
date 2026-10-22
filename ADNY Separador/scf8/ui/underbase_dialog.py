from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from packages.core.models.channel_info import ChannelInfo
from scf8.core.naming import separation_display_name
from scf8.services.underbase import LiveUnderbaseSettings, UnderbaseMode, is_underbase_channel
from scf8.ui.ss4_dialog_style import dialog_qss, help_button, pill_button, title_label

TITLE = "Propriedades da base branca dinâmica"
SUBTITLE = "Escolha a(s) separação(ões), as opções de base branca e clique em Criar dinâmica"
HEADERS = ("Separação(ões)", "Combinar", "Aplicar a todas", "Recuo", "Estilo")

HELP_TEXT = (
    "Marque ou desmarque as separações que entram na base branca.\n\n"
    "Recuo (pt): puxa a borda da base branca para dentro. Estilo: Real segue os dados da separação; "
    "Sólido imprime 100% onde houver cor.\n\n"
    "Criar dinâmica: a base branca é refeita automaticamente quando as separações mudam. "
    "Criar estática: a base branca fica como foi criada. Abra esta janela de novo para editar e atualizar."
)

_EXTRA_QSS = """
QPushButton#ub_style_actual, QPushButton#ub_style_solid {
  background: #e8e8e8; border: 3px solid #2b2b2b; min-width: 30px; min-height: 30px; padding: 0; }
QPushButton#ub_style_actual:checked, QPushButton#ub_style_solid:checked { border-color: #2fa84f; }
QLabel#ub_header { color: #e6e6e6; padding: 2px 6px; }
"""


def _style_icon(solid: bool, size: int = 28) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("#f2f2f2"))
    if not solid:
        painter = QPainter(pixmap)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#111111"))
        step = 4
        for y in range(0, size, step):
            for x in range(0, size, step):
                if x > y and (x // step + y // step) % 2 == 0:
                    painter.drawRect(x, y, step - 1, step - 1)
        painter.setPen(QColor("#111111"))
        painter.drawPolygon(QPolygon([pixmap.rect().topLeft(), pixmap.rect().topRight(), pixmap.rect().bottomRight()]))
        painter.end()
    return QIcon(pixmap)


def _swatch(rgb: tuple[int, int, int]) -> QLabel:
    label = QLabel()
    label.setFixedSize(30, 30)
    r, g, b = rgb
    label.setStyleSheet(f"background: rgb({r}, {g}, {b}); border: 1px solid #555;")
    return label


class LiveUnderbaseDialog(QDialog):
    """SS4 'Live Underbase Properties' (Create Underbase... / botão Underbase...).

    Reabrir com uma Underbase no documento mostra as opções dela; os botões Create Static /
    Create Live gravam o modo (``result_mode``) e aceitam.
    """

    def __init__(
        self,
        parent,
        channels: list[ChannelInfo],
        *,
        settings: LiveUnderbaseSettings | None = None,
        mode: UnderbaseMode = "live",
    ) -> None:
        super().__init__(parent)
        settings = settings or LiveUnderbaseSettings()
        self._mode: UnderbaseMode = mode
        self._min_density = settings.min_density
        self.setObjectName("ss4_live_underbase")
        self.setWindowTitle(TITLE)
        self.setModal(True)
        self.setStyleSheet(dialog_qss("ss4_live_underbase") + _EXTRA_QSS)

        layout = QVBoxLayout(self)
        layout.addWidget(title_label(TITLE))
        subtitle = QLabel(SUBTITLE)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        panel = QFrame()
        panel.setObjectName("ss4_panel")
        grid = QGridLayout(panel)
        grid.setHorizontalSpacing(14)
        for col, text in enumerate(HEADERS):
            header = QLabel(text)
            header.setObjectName("ub_header")
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(header, 0, col)

        self.combine_cb = QCheckBox()
        self.combine_cb.setObjectName("ub_combine")
        self.combine_cb.setToolTip("Combinar")
        self.combine_cb.setChecked(settings.combine)
        grid.addWidget(self.combine_cb, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        self.apply_all_cb = QCheckBox()
        self.apply_all_cb.setObjectName("ub_apply_all")
        self.apply_all_cb.setToolTip("Aplicar a todas")
        self.apply_all_cb.setChecked(settings.apply_to_all)
        grid.addWidget(self.apply_all_cb, 1, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        self.choke_spin = QDoubleSpinBox()
        self.choke_spin.setObjectName("ub_choke")
        self.choke_spin.setRange(0.0, 2.0)
        self.choke_spin.setSingleStep(0.05)
        self.choke_spin.setDecimals(2)
        self.choke_spin.setSuffix(" pt")
        self.choke_spin.setValue(settings.choke_pt)
        grid.addWidget(self.choke_spin, 1, 3, alignment=Qt.AlignmentFlag.AlignCenter)

        style_box = QWidget()
        style_row = QHBoxLayout(style_box)
        style_row.setContentsMargins(0, 0, 0, 0)
        self.style_solid = self._style_button("ub_style_solid", "Sólido", solid=True)
        self.style_actual = self._style_button("ub_style_actual", "Real", solid=False)
        self._style_group = QButtonGroup(self)
        self._style_group.setExclusive(True)
        for button in (self.style_solid, self.style_actual):
            self._style_group.addButton(button)
            style_row.addWidget(button)
        (self.style_solid if settings.style == "solid" else self.style_actual).setChecked(True)
        grid.addWidget(style_box, 1, 4, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(panel)

        rows = QWidget()
        rows_layout = QGridLayout(rows)
        rows_layout.setHorizontalSpacing(10)
        self.separation_boxes: dict[str, QCheckBox] = {}
        for row, ch in enumerate(channels):
            rows_layout.addWidget(_swatch(tuple(ch.color_rgb)), row, 0)
            rows_layout.addWidget(QLabel(separation_display_name(ch.name)), row, 1)
            box = QCheckBox()
            box.setObjectName(f"ub_sep:{ch.id}")
            if is_underbase_channel(ch):
                box.setChecked(True)
                box.setEnabled(False)
                box.setToolTip("A própria base branca")
            else:
                box.setChecked(ch.id not in settings.excluded)
            rows_layout.addWidget(box, row, 2)
            self.separation_boxes[ch.id] = box
        rows_layout.setColumnStretch(3, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: #1e1e1e; }")
        scroll.setWidget(rows)
        scroll.setMinimumHeight(min(440, 44 * max(1, len(channels)) + 8))
        layout.addWidget(scroll, stretch=1)

        buttons = QHBoxLayout()
        buttons.addWidget(help_button(self, TITLE, HELP_TEXT))
        buttons.addStretch(1)
        cancel = pill_button("Cancelar", "red")
        cancel.clicked.connect(self.reject)
        static = pill_button("Criar estática", "green_outline")
        static.clicked.connect(lambda: self._finish("static"))
        live = pill_button("Criar dinâmica", "green")
        live.setDefault(True)
        live.clicked.connect(lambda: self._finish("live"))
        for button in (cancel, static, live):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.resize(560, 620)

    def _style_button(self, name: str, tooltip: str, *, solid: bool) -> QPushButton:
        button = QPushButton()
        button.setObjectName(name)
        button.setCheckable(True)
        button.setToolTip(tooltip)
        button.setIcon(_style_icon(solid))
        button.setIconSize(QSize(28, 28))
        return button

    def _finish(self, mode: UnderbaseMode) -> None:
        self._mode = mode
        self.accept()

    def result_mode(self) -> UnderbaseMode:
        return self._mode

    def settings(self) -> LiveUnderbaseSettings:
        excluded = frozenset(cid for cid, box in self.separation_boxes.items() if box.isEnabled() and not box.isChecked())
        return LiveUnderbaseSettings(
            excluded=excluded,
            combine=self.combine_cb.isChecked(),
            apply_to_all=self.apply_all_cb.isChecked(),
            choke_pt=float(self.choke_spin.value()),
            style="solid" if self.style_solid.isChecked() else "actual",
            min_density=self._min_density,
        )
