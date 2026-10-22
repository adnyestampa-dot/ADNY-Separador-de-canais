from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
import os

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QSpinBox,
    QVBoxLayout,
)

SYSTEM_DEFAULT_PRINTER = "System default"
MEDIA_CHOICES: tuple[tuple[str, str], ...] = (
    ("Filme", "Film"),
    ("Vegetal", "Vellum"),
    ("Papel", "Paper"),
)
DOT_SHAPE_CHOICES: tuple[tuple[str, str], ...] = (
    ("Elíptico", "Elliptical"),
    ("Redondo", "Round"),
    ("Quadrado", "Square"),
)
DEFAULT_PREFERENCES_PATH = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "ADNY Separador" / "preferences.ini"
_GROUP = "default_printer"


@dataclass
class PrinterDefaults:
    printer: str = SYSTEM_DEFAULT_PRINTER
    media: str = "Film"
    dpi: int = 1200
    lpi: int = 55
    angle: float = 22.5
    dot_shape: str = "Elliptical"
    registration_marks: bool = True
    separation_names: bool = True
    emulsion_down: bool = False
    negative: bool = False


def _settings(path: Path | str) -> QSettings:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return QSettings(str(path), QSettings.Format.IniFormat)


def load_printer_defaults(path: Path | str = DEFAULT_PREFERENCES_PATH) -> PrinterDefaults:
    store = _settings(path)
    store.beginGroup(_GROUP)
    base = PrinterDefaults()
    values = {}
    for f in fields(PrinterDefaults):
        default = getattr(base, f.name)
        raw = store.value(f.name, default)
        if isinstance(default, bool):
            values[f.name] = raw if isinstance(raw, bool) else str(raw).lower() in ("true", "1")
        else:
            try:
                values[f.name] = type(default)(raw)
            except (TypeError, ValueError):
                values[f.name] = default
    store.endGroup()
    return PrinterDefaults(**values)


def save_printer_defaults(values: PrinterDefaults, path: Path | str = DEFAULT_PREFERENCES_PATH) -> None:
    store = _settings(path)
    store.beginGroup(_GROUP)
    for key, value in asdict(values).items():
        store.setValue(key, value)
    store.endGroup()
    store.sync()


def _available_printers() -> list[str]:
    try:
        from PySide6.QtPrintSupport import QPrinterInfo

        return list(QPrinterInfo.availablePrinterNames())
    except Exception:  # noqa: BLE001 - sem suporte de impressão no sistema
        return []


def _combo_set_data(combo: QComboBox, value: str, choices: tuple[tuple[str, str], ...]) -> None:
    idx = combo.findData(value)
    if idx >= 0:
        combo.setCurrentIndex(idx)
        return
    label = next((lbl for lbl, data in choices if data == value), value)
    combo.addItem(label, value)
    combo.setCurrentIndex(combo.count() - 1)


class PrinterSettingsDialog(QDialog):
    """Edit > Default Printer Settings...: padrões de saída de filme usados pelo Print Commander."""

    def __init__(self, parent, initial: PrinterDefaults | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Impressora padrão")
        init = initial or PrinterDefaults()
        layout = QVBoxLayout(self)

        output = QGroupBox("Dispositivo de saída")
        form = QFormLayout(output)
        self.printer_combo = QComboBox()
        self.printer_combo.addItem("Padrão do sistema", SYSTEM_DEFAULT_PRINTER)
        for name in _available_printers():
            self.printer_combo.addItem(name, name)
        if init.printer not in (SYSTEM_DEFAULT_PRINTER, *_available_printers()):
            self.printer_combo.addItem(init.printer, init.printer)
        _combo_set_data(self.printer_combo, init.printer, (("Padrão do sistema", SYSTEM_DEFAULT_PRINTER),))
        form.addRow("Impressora:", self.printer_combo)
        self.media_combo = QComboBox()
        for label, value in MEDIA_CHOICES:
            self.media_combo.addItem(label, value)
        _combo_set_data(self.media_combo, init.media, MEDIA_CHOICES)
        form.addRow("Mídia:", self.media_combo)
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(150, 4800)
        self.dpi_spin.setSingleStep(150)
        self.dpi_spin.setSuffix(" dpi")
        self.dpi_spin.setValue(init.dpi)
        form.addRow("Resolução:", self.dpi_spin)
        layout.addWidget(output)

        halftone = QGroupBox("Meio-tom")
        form = QFormLayout(halftone)
        self.lpi_spin = QSpinBox()
        self.lpi_spin.setRange(10, 150)
        self.lpi_spin.setSuffix(" lpi")
        self.lpi_spin.setValue(init.lpi)
        form.addRow("Frequência:", self.lpi_spin)
        self.angle_spin = QDoubleSpinBox()
        self.angle_spin.setRange(0.0, 90.0)
        self.angle_spin.setDecimals(1)
        self.angle_spin.setSuffix("°")
        self.angle_spin.setValue(init.angle)
        form.addRow("Ângulo:", self.angle_spin)
        self.dot_combo = QComboBox()
        for label, value in DOT_SHAPE_CHOICES:
            self.dot_combo.addItem(label, value)
        _combo_set_data(self.dot_combo, init.dot_shape, DOT_SHAPE_CHOICES)
        form.addRow("Formato do ponto:", self.dot_combo)
        layout.addWidget(halftone)

        marks = QGroupBox("Opções de filme")
        box = QVBoxLayout(marks)
        self.registration_cb = QCheckBox("Marcas de registro")
        self.registration_cb.setChecked(init.registration_marks)
        self.names_cb = QCheckBox("Nomes das separações")
        self.names_cb.setChecked(init.separation_names)
        self.emulsion_cb = QCheckBox("Emulsão para baixo (espelhar)")
        self.emulsion_cb.setChecked(init.emulsion_down)
        self.negative_cb = QCheckBox("Negativo")
        self.negative_cb.setChecked(init.negative)
        for cb in (self.registration_cb, self.names_cb, self.emulsion_cb, self.negative_cb):
            box.addWidget(cb)
        layout.addWidget(marks)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Aceitar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> PrinterDefaults:
        printer_data = self.printer_combo.currentData()
        printer = str(printer_data if printer_data is not None else self.printer_combo.currentText())
        media = str(self.media_combo.currentData())
        dot_shape = str(self.dot_combo.currentData())
        return PrinterDefaults(
            printer=printer,
            media=media,
            dpi=int(self.dpi_spin.value()),
            lpi=int(self.lpi_spin.value()),
            angle=float(self.angle_spin.value()),
            dot_shape=dot_shape,
            registration_marks=self.registration_cb.isChecked(),
            separation_names=self.names_cb.isChecked(),
            emulsion_down=self.emulsion_cb.isChecked(),
            negative=self.negative_cb.isChecked(),
        )
