from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from packages.core.models.project_state import TextilePreset


class TextilesDock(QDockWidget):
    preset_changed = Signal(str)

    PRESETS = [
        TextilePreset.PRETO,
        TextilePreset.BRANCO,
        TextilePreset.CINZA_NEUTRO,
        TextilePreset.MARINHO,
    ]

    def __init__(self, parent=None) -> None:
        super().__init__("Tecidos / Ground", parent)
        self.setObjectName("dock_textiles")

        container = QWidget()
        layout = QVBoxLayout(container)
        self._buttons: dict[str, QPushButton] = {}

        for preset in self.PRESETS:
            btn = QPushButton(preset.value)
            btn.clicked.connect(lambda checked=False, p=preset: self.preset_changed.emit(p.value))
            layout.addWidget(btn)
            self._buttons[preset.value] = btn

        layout.addStretch()
        self.setWidget(container)

    def set_active_preset(self, preset_name: str) -> None:
        for name, btn in self._buttons.items():
            btn.setProperty("primary", name == preset_name)
            style = btn.style()
            style.unpolish(btn)
            style.polish(btn)
