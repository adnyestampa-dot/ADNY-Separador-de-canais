from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from packages.core.models.project_state import TextilePreset
from packages.image.textile import GROUND_COLORS, ground_color_for_preset

CUSTOM_KEY = "custom"
TEXTILE_KEY = "textile:"


class GroundColorDialog(QDialog):
    """View > Textile... / botão Textile...: tecido do documento (presets, Custom Textiles) ou cor personalizada."""

    def __init__(
        self,
        parent=None,
        *,
        preset: TextilePreset = TextilePreset.PRETO,
        custom_rgb: tuple[int, int, int] | None = None,
        textiles: list[tuple[str, tuple[int, int, int]]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tecidos")
        self._custom_rgb: tuple[int, int, int] = custom_rgb or ground_color_for_preset(preset)
        self._textiles = [(name, tuple(int(c) for c in rgb)) for name, rgb in (textiles or [])]

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.combo = QComboBox()
        for item in GROUND_COLORS:
            self.combo.addItem(item.value, item.value)
        for i, (name, _rgb) in enumerate(self._textiles):
            self.combo.addItem(name, f"{TEXTILE_KEY}{i}")
        self.combo.addItem("Personalizado", CUSTOM_KEY)
        self.combo.setCurrentIndex(self.combo.findData(self._initial_key(preset, custom_rgb)))
        self.combo.currentIndexChanged.connect(self._update_swatch)
        form.addRow("Tecido:", self.combo)

        row = QHBoxLayout()
        self.swatch = QLabel()
        self.swatch.setFixedSize(48, 24)
        row.addWidget(self.swatch)
        self.custom_btn = QPushButton("Cor personalizada…")
        self.custom_btn.clicked.connect(self._pick_custom)
        row.addWidget(self.custom_btn)
        row.addStretch()
        form.addRow("Cor:", row)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Aceitar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_swatch()

    def _initial_key(self, preset: TextilePreset, custom_rgb: tuple[int, int, int] | None) -> str:
        if custom_rgb is None:
            return preset.value
        match = next((i for i, (_n, rgb) in enumerate(self._textiles) if rgb == tuple(custom_rgb)), None)
        return CUSTOM_KEY if match is None else f"{TEXTILE_KEY}{match}"

    def _pick_custom(self) -> None:
        picked = QColorDialog.getColor(QColor(*self._custom_rgb), self, "Cor do tecido")
        if not picked.isValid():
            return
        self._custom_rgb = (picked.red(), picked.green(), picked.blue())
        self.combo.setCurrentIndex(self.combo.findData(CUSTOM_KEY))
        self._update_swatch()

    def _update_swatch(self) -> None:
        r, g, b = self.ground_rgb()
        self.swatch.setStyleSheet(f"background: rgb({r}, {g}, {b}); border: 1px solid #888;")

    def _textile_index(self) -> int | None:
        key = str(self.combo.currentData())
        return int(key[len(TEXTILE_KEY):]) if key.startswith(TEXTILE_KEY) else None

    def selected_preset(self) -> TextilePreset | None:
        """Preset escolhido; None para um tecido custom ou a cor personalizada."""
        key = self.combo.currentData()
        if key == CUSTOM_KEY or self._textile_index() is not None:
            return None
        return TextilePreset(key)

    def selected_textile(self) -> str | None:
        """Nome do tecido da biblioteca Custom Textiles escolhido (None nos outros casos)."""
        index = self._textile_index()
        return self._textiles[index][0] if index is not None else None

    def custom_rgb(self) -> tuple[int, int, int] | None:
        index = self._textile_index()
        if index is not None:
            return self._textiles[index][1]  # type: ignore[return-value]
        return self._custom_rgb if self.selected_preset() is None else None

    def ground_rgb(self) -> tuple[int, int, int]:
        preset = self.selected_preset()
        return self.custom_rgb() or self._custom_rgb if preset is None else ground_color_for_preset(preset)
