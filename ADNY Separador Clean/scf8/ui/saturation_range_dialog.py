from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from scf8.widgets.ink_checkbox import InkCheckBox

TITLE = "Ajuste por faixa de saturação"

HELP_TEXT = (
    "Encharcar: intensifica os valores de cor, escurecendo os positivos de filme para passar mais tinta na mesa.\n\n"
    "Aliviar tinta: remove dados a partir do 1% (valor mínimo presente na separação).\n\n"
    "Dica: na separação Branco Brilho, um corte pequeno em Aliviar tinta (comece com 95) melhora a cor."
)

_QSS = """
QDialog#ss4_saturation_range { background: #1e1e1e; }
QDialog#ss4_saturation_range QLabel { color: #e6e6e6; }
QLabel#ss4_dialog_title { font-size: 15px; padding: 2px 0 6px 0; }
QDialog#ss4_saturation_range QSpinBox { background: #ffffff; color: #000000; min-width: 52px; }
QPushButton#ss4_help { color: #9a9a9a; border: 2px solid #4a4a4a; border-radius: 13px;
  min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; font-weight: bold; }
QPushButton#pill_red { color: #f0f0f0; background: #1e1e1e; border: 2px solid #e02a2a;
  border-radius: 12px; padding: 3px 14px; }
QPushButton#pill_green { color: #f0f0f0; background: #157a1f; border: 2px solid #157a1f;
  border-radius: 12px; padding: 3px 14px; }
"""


class SaturationRangeDialog(QDialog):
    """SS4 'Adjust by Saturation Range' — High Saturation (padrão 0) e Low Saturation (padrão 100).

    Com ``separations`` mostra a linha de caixas coloridas (uma por separação): só as
    marcadas são alteradas.
    """

    range_changed = Signal(int, int)

    def __init__(
        self,
        parent=None,
        *,
        subtitle: str = "",
        separations: list[tuple[str, tuple[int, int, int], str]] | None = None,
        checked_ids: set[str] | list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ss4_saturation_range")
        self.setWindowTitle(TITLE)
        self.setModal(True)
        self.setStyleSheet(_QSS)
        layout = QVBoxLayout(self)
        title = QLabel(TITLE)
        title.setObjectName("ss4_dialog_title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sub.setStyleSheet("color: #9a9a9a;")
            layout.addWidget(sub)

        grid = QGridLayout()
        self.high_spin, self.high_slider = self._row(grid, 0, "Encharcar:", 0)
        self.low_spin, self.low_slider = self._row(grid, 1, "Aliviar tinta:", 100)
        layout.addLayout(grid)

        self.separation_boxes: dict[str, InkCheckBox] = {}
        checked = set(checked_ids) if checked_ids is not None else None
        buttons = QHBoxLayout()
        for cid, rgb, name in separations or ():
            box = InkCheckBox(cid, rgb, name)
            box.setObjectName(f"sat_sep:{cid}")
            box.setChecked(checked is None or cid in checked)
            box.toggled.connect(lambda _on: self._emit_timer.start())
            buttons.addWidget(box)
            self.separation_boxes[cid] = box
        help_btn = QPushButton("?")
        help_btn.setObjectName("ss4_help")
        help_btn.setToolTip("Ajuda")
        help_btn.clicked.connect(lambda: QMessageBox.information(self, TITLE, HELP_TEXT))
        if not self.separation_boxes:
            buttons.addWidget(help_btn)
        buttons.addStretch(1)
        cancel = QPushButton("Cancelar")
        cancel.setObjectName("pill_red")
        cancel.clicked.connect(self.reject)
        accept = QPushButton("Aceitar")
        accept.setObjectName("pill_green")
        accept.setDefault(True)
        accept.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(accept)
        layout.addLayout(buttons)
        if self.separation_boxes:
            layout.addWidget(help_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._emit_timer = QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.setInterval(120)
        self._emit_timer.timeout.connect(lambda: self.range_changed.emit(self.high(), self.low()))
        self.finished.connect(lambda _r: self._emit_timer.stop())

    def _row(self, grid: QGridLayout, row: int, label: str, value: int):
        grid.addWidget(QLabel(label), row, 0)
        spin = QSpinBox()
        spin.setRange(0, 100)
        spin.setValue(value)
        grid.addWidget(spin, row, 1)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(value)
        slider.setTickPosition(QSlider.TickPosition.TicksAbove)
        slider.setTickInterval(10)
        slider.setMinimumWidth(220)
        grid.addWidget(slider, row, 2)
        spin.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(spin.setValue)
        slider.valueChanged.connect(lambda _v: self._emit_timer.start())
        return spin, slider

    def high(self) -> int:
        return int(self.high_slider.value())

    def low(self) -> int:
        return int(self.low_slider.value())

    def is_identity(self) -> bool:
        return self.high() == 0 and self.low() == 100

    def checked_ids(self) -> list[str] | None:
        """Separações marcadas na linha de caixas; None quando o diálogo não tem caixas."""
        if not self.separation_boxes:
            return None
        return [cid for cid, box in self.separation_boxes.items() if box.isChecked()]
