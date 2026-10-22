from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from packages.image.channel_adjust import ChannelAdjustments


class _SliderRow(QWidget):
    """Linha com label, barra deslizante e valor numérico."""

    value_changed = Signal()

    def __init__(
        self,
        title: str,
        minimum: int,
        maximum: int,
        value: int,
        format_value: Callable[[int], str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._format = format_value

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        title_lbl = QLabel(title)
        title_lbl.setMinimumWidth(110)
        layout.addWidget(title_lbl)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.slider.setTracking(True)
        self.slider.setPageStep(max(1, (maximum - minimum) // 20))
        layout.addWidget(self.slider, stretch=1)

        self.value_lbl = QLabel(format_value(value))
        self.value_lbl.setMinimumWidth(42)
        self.value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.value_lbl)

        self.slider.valueChanged.connect(self._on_change)

    def _on_change(self, val: int) -> None:
        self.value_lbl.setText(self._format(val))
        self.value_changed.emit()

    def int_value(self) -> int:
        return self.slider.value()


class ChannelAdjustDialog(QDialog):
    """Ajuste por canal com barras deslizantes e preview em tempo real."""

    adjustments_changed = Signal(object)

    def __init__(
        self,
        channel_name: str,
        adjustments: ChannelAdjustments,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Ajustar — {channel_name}")
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Arraste as barras para ajustar. O preview atualiza em tempo real.\n"
            "High Saturation aumenta dados médios/altos. "
            "Low Saturation remove dados fracos. "
            "Tint escala uniformemente. Choke recua bordas (0–30 px)."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #aaa; font-size: 11px; margin-bottom: 6px;")
        layout.addWidget(intro)

        self.high_sat = _SliderRow(
            "High Saturation",
            0,
            200,
            int(round(adjustments.high_saturation * 100)),
            lambda v: f"{v / 100:.2f}",
        )
        layout.addWidget(self.high_sat)

        self.low_sat = _SliderRow(
            "Low Saturation",
            0,
            200,
            int(round(adjustments.low_saturation * 100)),
            lambda v: f"{v / 100:.2f}",
        )
        layout.addWidget(self.low_sat)

        self.tint = _SliderRow(
            "Tint",
            0,
            200,
            int(round(adjustments.tint * 100)),
            lambda v: f"{v / 100:.2f}",
        )
        layout.addWidget(self.tint)

        self.choke = _SliderRow(
            "Choke",
            0,
            30,
            int(adjustments.choke),
            lambda v: f"{v}",
        )
        layout.addWidget(self.choke)

        for row in (self.high_sat, self.low_sat, self.tint, self.choke):
            row.value_changed.connect(self._emit_live)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("OK")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _emit_live(self) -> None:
        self.adjustments_changed.emit(self.get_adjustments())

    def get_adjustments(self) -> ChannelAdjustments:
        return ChannelAdjustments(
            high_saturation=self.high_sat.int_value() / 100.0,
            low_saturation=self.low_sat.int_value() / 100.0,
            tint=self.tint.int_value() / 100.0,
            choke=self.choke.int_value(),
        )
