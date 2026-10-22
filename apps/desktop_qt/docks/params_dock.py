from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

MODES = ["auto", "default", "oceano", "fogo", "natureza", "realismo", "quadrinhos"]


class ParamsDock(QDockWidget):
    """Parâmetros públicos do fluxo único FAV8+."""

    def __init__(self, parent=None) -> None:
        super().__init__("Parâmetros FAV8+", parent)
        self.setObjectName("dock_params")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Motor: FAV8+"))
        layout.addWidget(QLabel("Arquétipo:"))

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(MODES)
        layout.addWidget(self.mode_combo)

        self.dark_fabric_cb = QCheckBox("Simular tecido escuro no preview")
        self.dark_fabric_cb.setChecked(True)
        layout.addWidget(self.dark_fabric_cb)

        layout.addWidget(QLabel("Key plate (canal Black):"))
        self.key_plate_enabled = QCheckBox("Ativar extração de key")
        layout.addWidget(self.key_plate_enabled)
        self.key_plate_mode = QComboBox()
        self.key_plate_mode.addItem("Automática", "auto")
        self.key_plate_mode.addItem("Override manual", "override")
        layout.addWidget(self.key_plate_mode)
        self.key_plate_threshold = QDoubleSpinBox()
        self.key_plate_threshold.setRange(0.01, 1.0)
        self.key_plate_threshold.setDecimals(3)
        self.key_plate_threshold.setValue(0.38)
        self.key_plate_threshold.setPrefix("Limiar tonal: ")
        layout.addWidget(self.key_plate_threshold)
        self.key_plate_gamma = QDoubleSpinBox()
        self.key_plate_gamma.setRange(0.01, 10.0)
        self.key_plate_gamma.setDecimals(3)
        self.key_plate_gamma.setValue(0.88)
        self.key_plate_gamma.setPrefix("Gamma: ")
        layout.addWidget(self.key_plate_gamma)
        self.key_plate_chroma = QDoubleSpinBox()
        self.key_plate_chroma.setRange(0.0, 1.0)
        self.key_plate_chroma.setDecimals(3)
        self.key_plate_chroma.setValue(0.035)
        self.key_plate_chroma.setPrefix("Proteção cromática: ")
        layout.addWidget(self.key_plate_chroma)
        self.key_plate_min_density = QDoubleSpinBox()
        self.key_plate_min_density.setRange(0.0, 1.0)
        self.key_plate_min_density.setDecimals(3)
        self.key_plate_min_density.setPrefix("Densidade mín.: ")
        layout.addWidget(self.key_plate_min_density)
        self.key_plate_max_density = QDoubleSpinBox()
        self.key_plate_max_density.setRange(0.0, 1.0)
        self.key_plate_max_density.setDecimals(3)
        self.key_plate_max_density.setValue(1.0)
        self.key_plate_max_density.setPrefix("Densidade máx.: ")
        layout.addWidget(self.key_plate_max_density)
        self.key_plate_merge = QCheckBox("Merge seguro com escuros compatíveis")
        layout.addWidget(self.key_plate_merge)

        layout.addWidget(QLabel("Limpeza conjunta:"))
        self.cleanup_mode = QComboBox()
        for label, value in (
            ("Desativada", "off"),
            ("Automática", "auto"),
            ("Manual", "manual"),
        ):
            self.cleanup_mode.addItem(label, value)
        layout.addWidget(self.cleanup_mode)
        self.cleanup_threshold = QDoubleSpinBox()
        self.cleanup_threshold.setRange(0, 1)
        self.cleanup_threshold.setDecimals(3)
        self.cleanup_threshold.setValue(0.03)
        self.cleanup_threshold.setPrefix("Threshold: ")
        layout.addWidget(self.cleanup_threshold)
        self.cleanup_min_area = QSpinBox()
        self.cleanup_min_area.setRange(1, 100_000)
        self.cleanup_min_area.setValue(4)
        self.cleanup_min_area.setPrefix("Área mínima: ")
        self.cleanup_min_area.setSuffix(" px")
        layout.addWidget(self.cleanup_min_area)
        layout.addStretch()
        self.setWidget(container)

    def apply_separation_params(self, params: dict) -> None:
        mode = params.get("mode")
        if mode:
            index = self.mode_combo.findText(mode)
            if index >= 0:
                self.mode_combo.setCurrentIndex(index)
        if "dark_fabric" in params:
            self.dark_fabric_cb.setChecked(bool(params["dark_fabric"]))
        if "key_plate_enabled" in params:
            self.key_plate_enabled.setChecked(bool(params["key_plate_enabled"]))
        if "key_plate_mode" in params:
            index = self.key_plate_mode.findData(params["key_plate_mode"])
            if index >= 0:
                self.key_plate_mode.setCurrentIndex(index)
        for name, widget in (
            ("key_plate_tonal_threshold", self.key_plate_threshold),
            ("key_plate_gamma", self.key_plate_gamma),
            ("key_plate_chroma_protection", self.key_plate_chroma),
            ("key_plate_min_density", self.key_plate_min_density),
            ("key_plate_max_density", self.key_plate_max_density),
        ):
            if name in params:
                widget.setValue(float(params[name]))
        if "key_plate_merge_compatible_dark" in params:
            self.key_plate_merge.setChecked(
                bool(params["key_plate_merge_compatible_dark"])
            )
        if "joint_cleanup_mode" in params:
            index = self.cleanup_mode.findData(params["joint_cleanup_mode"])
            if index >= 0:
                self.cleanup_mode.setCurrentIndex(index)
        if "joint_cleanup_threshold" in params:
            self.cleanup_threshold.setValue(float(params["joint_cleanup_threshold"]))
        if "joint_cleanup_min_area_px" in params:
            self.cleanup_min_area.setValue(int(params["joint_cleanup_min_area_px"]))

    def get_separation_params(self) -> dict:
        return {
            "engine": "fav8_plus",
            "mode": self.mode_combo.currentText(),
            "dark_fabric": self.dark_fabric_cb.isChecked(),
            "key_plate_enabled": self.key_plate_enabled.isChecked(),
            "key_plate_mode": self.key_plate_mode.currentData() or "auto",
            "key_plate_tonal_threshold": self.key_plate_threshold.value(),
            "key_plate_gamma": self.key_plate_gamma.value(),
            "key_plate_chroma_protection": self.key_plate_chroma.value(),
            "key_plate_min_density": self.key_plate_min_density.value(),
            "key_plate_max_density": self.key_plate_max_density.value(),
            "key_plate_merge_compatible_dark": self.key_plate_merge.isChecked(),
            "joint_cleanup_mode": self.cleanup_mode.currentData() or "off",
            "joint_cleanup_threshold": self.cleanup_threshold.value(),
            "joint_cleanup_min_area_px": self.cleanup_min_area.value(),
        }
