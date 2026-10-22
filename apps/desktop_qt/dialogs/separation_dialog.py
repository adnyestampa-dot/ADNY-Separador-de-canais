from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

MODES = ["auto", "default", "oceano", "fogo", "natureza", "realismo", "quadrinhos"]
MODE_LABELS = {
    "auto": "Automático (recomendado)",
    "default": "Padrão",
    "oceano": "Oceano",
    "fogo": "Fogo",
    "natureza": "Natureza",
    "realismo": "Realismo",
    "quadrinhos": "Quadrinhos",
}


class SeparationDialog(QDialog):
    """Configuração de modo e tecido do motor único FAV8+."""

    def __init__(self, parent: QWidget | None = None, defaults: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Separar Canais — FAV8+")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        defaults = defaults or {}
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Motor FAV8+. O modo automático analisa a arte; escolha outro arquétipo "
            "para fazer override manual."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        layout.addWidget(QLabel("Arquétipo:"))
        self.mode_combo = QComboBox()
        for mode in MODES:
            self.mode_combo.addItem(MODE_LABELS[mode], mode)
        index = self.mode_combo.findData(defaults.get("mode", "auto"))
        self.mode_combo.setCurrentIndex(max(index, 0))
        layout.addWidget(self.mode_combo)

        self.dark_fabric_cb = QCheckBox("Simular tecido escuro no preview")
        self.dark_fabric_cb.setChecked(bool(defaults.get("dark_fabric", True)))
        layout.addWidget(self.dark_fabric_cb)

        layout.addWidget(QLabel("Key plate (promove o canal Black existente):"))
        self.key_enabled = QCheckBox("Ativar key plate")
        self.key_enabled.setChecked(bool(defaults.get("key_plate_enabled", False)))
        layout.addWidget(self.key_enabled)
        self.key_mode = QComboBox()
        self.key_mode.addItem("Automática", "auto")
        self.key_mode.addItem("Override manual", "override")
        self.key_mode.setCurrentIndex(
            max(self.key_mode.findData(defaults.get("key_plate_mode", "auto")), 0)
        )
        layout.addWidget(self.key_mode)
        self.key_threshold = QDoubleSpinBox()
        self.key_threshold.setRange(0.01, 1.0)
        self.key_threshold.setDecimals(3)
        self.key_threshold.setValue(float(defaults.get("key_plate_tonal_threshold", 0.38)))
        self.key_threshold.setPrefix("Limiar tonal: ")
        layout.addWidget(self.key_threshold)
        self.key_gamma = QDoubleSpinBox()
        self.key_gamma.setRange(0.01, 10.0)
        self.key_gamma.setDecimals(3)
        self.key_gamma.setValue(float(defaults.get("key_plate_gamma", 0.88)))
        self.key_gamma.setPrefix("Gamma: ")
        layout.addWidget(self.key_gamma)
        self.key_chroma = QDoubleSpinBox()
        self.key_chroma.setRange(0.0, 1.0)
        self.key_chroma.setDecimals(3)
        self.key_chroma.setValue(float(defaults.get("key_plate_chroma_protection", 0.035)))
        self.key_chroma.setPrefix("Proteção cromática: ")
        layout.addWidget(self.key_chroma)
        self.key_min_density = QDoubleSpinBox()
        self.key_min_density.setRange(0.0, 1.0)
        self.key_min_density.setDecimals(3)
        self.key_min_density.setValue(float(defaults.get("key_plate_min_density", 0.0)))
        self.key_min_density.setPrefix("Densidade mín.: ")
        layout.addWidget(self.key_min_density)
        self.key_max_density = QDoubleSpinBox()
        self.key_max_density.setRange(0.0, 1.0)
        self.key_max_density.setDecimals(3)
        self.key_max_density.setValue(float(defaults.get("key_plate_max_density", 1.0)))
        self.key_max_density.setPrefix("Densidade máx.: ")
        layout.addWidget(self.key_max_density)
        self.key_merge = QCheckBox("Merge seguro com canal escuro compatível")
        self.key_merge.setChecked(
            bool(defaults.get("key_plate_merge_compatible_dark", False))
        )
        layout.addWidget(self.key_merge)

        layout.addWidget(QLabel("Limpeza conjunta:"))
        self.cleanup_mode = QComboBox()
        self.cleanup_mode.addItem("Desativada (paridade)", "off")
        self.cleanup_mode.addItem("Automática (DPI/LPI quando disponíveis)", "auto")
        self.cleanup_mode.addItem("Override manual", "manual")
        cleanup_index = self.cleanup_mode.findData(defaults.get("joint_cleanup_mode", "off"))
        self.cleanup_mode.setCurrentIndex(max(cleanup_index, 0))
        layout.addWidget(self.cleanup_mode)

        self.cleanup_threshold = QDoubleSpinBox()
        self.cleanup_threshold.setRange(0.0, 1.0)
        self.cleanup_threshold.setDecimals(3)
        self.cleanup_threshold.setSingleStep(0.005)
        self.cleanup_threshold.setValue(float(defaults.get("joint_cleanup_threshold", 0.03)))
        self.cleanup_threshold.setPrefix("Threshold: ")
        layout.addWidget(self.cleanup_threshold)

        self.cleanup_min_area = QSpinBox()
        self.cleanup_min_area.setRange(1, 100_000)
        self.cleanup_min_area.setValue(int(defaults.get("joint_cleanup_min_area_px", 4)))
        self.cleanup_min_area.setPrefix("Área mínima: ")
        self.cleanup_min_area.setSuffix(" px")
        layout.addWidget(self.cleanup_min_area)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText("Separar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_params(self) -> dict[str, Any]:
        return {
            "engine": "fav8_plus",
            "mode": self.mode_combo.currentData() or "auto",
            "dark_fabric": self.dark_fabric_cb.isChecked(),
            "key_plate_enabled": self.key_enabled.isChecked(),
            "key_plate_mode": self.key_mode.currentData() or "auto",
            "key_plate_tonal_threshold": self.key_threshold.value(),
            "key_plate_gamma": self.key_gamma.value(),
            "key_plate_chroma_protection": self.key_chroma.value(),
            "key_plate_min_density": self.key_min_density.value(),
            "key_plate_max_density": self.key_max_density.value(),
            "key_plate_merge_compatible_dark": self.key_merge.isChecked(),
            "joint_cleanup_mode": self.cleanup_mode.currentData() or "off",
            "joint_cleanup_threshold": self.cleanup_threshold.value(),
            "joint_cleanup_min_area_px": self.cleanup_min_area.value(),
        }


def ask_separation_params(parent: QWidget | None, params_dock: Any) -> dict[str, Any] | None:
    host = parent or QApplication.activeWindow()
    dialog = SeparationDialog(host, params_dock.get_separation_params())
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    chosen = dialog.get_params()
    params_dock.apply_separation_params(chosen)
    return chosen
