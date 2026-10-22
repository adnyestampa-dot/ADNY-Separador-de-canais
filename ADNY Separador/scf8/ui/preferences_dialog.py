from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from scf8.ui.ss4_dialog_style import dialog_qss, help_button, pill_button, title_label

TITLE = "Preferências"
DEFAULT_VIEW = "ink"
DEFAULT_UNDO_LIMIT = 10
DEFAULT_PRESS_SIZE = 6
PRESS_SIZE_RANGE = (2, 16)

HELP_TEXT = (
    "Visualização padrão das separações: Tinta mostra cada separação na cor da tinta; "
    "Filme em preto e branco.\n\n"
    "Limite do desfazer: quantos passos o Desfazer pode voltar.\n\n"
    "Telas padrão na mesa: quantidade de telas com que o Encaixe na mesa abre."
)


class PreferencesDialog(QDialog):
    """SS4 Preferences: Default Separation View (Ink/Film), Undo Limit, Default Press Size.

    O botão Accept só aparece depois que algo muda; Close fecha sem aplicar.
    """

    def __init__(
        self,
        parent,
        *,
        default_view: str = DEFAULT_VIEW,
        undo_limit: int = DEFAULT_UNDO_LIMIT,
        press_size: int = DEFAULT_PRESS_SIZE,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ss4_preferences")
        self.setWindowTitle(TITLE)
        self.setModal(True)
        self.setStyleSheet(dialog_qss("ss4_preferences"))
        layout = QVBoxLayout(self)
        layout.addWidget(title_label(TITLE))

        view_panel = self._panel(layout)
        view_layout = QVBoxLayout(view_panel)
        heading = QLabel("Visualização padrão das separações")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        view_layout.addWidget(heading)
        self.view_combo = QComboBox()
        self.view_combo.setObjectName("pref_view")
        self.view_combo.addItem("Tinta", "ink")
        self.view_combo.addItem("Filme", "film")
        self.view_combo.setCurrentIndex(max(0, self.view_combo.findData(default_view)))
        view_layout.addWidget(self.view_combo, alignment=Qt.AlignmentFlag.AlignCenter)

        numbers_panel = self._panel(layout)
        form = QFormLayout(numbers_panel)
        form.setFormAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.undo_spin = QSpinBox()
        self.undo_spin.setObjectName("pref_undo_limit")
        self.undo_spin.setRange(1, 100)
        self.undo_spin.setValue(int(undo_limit))
        form.addRow("Limite do desfazer:", self.undo_spin)
        self.press_spin = QSpinBox()
        self.press_spin.setObjectName("pref_press_size")
        self.press_spin.setRange(*PRESS_SIZE_RANGE)
        self.press_spin.setValue(int(press_size))
        form.addRow("Telas padrão na mesa:", self.press_spin)

        buttons = QHBoxLayout()
        buttons.addWidget(help_button(self, TITLE, HELP_TEXT))
        buttons.addStretch(1)
        self.accept_btn = pill_button("Aceitar", "green")
        self.accept_btn.clicked.connect(self.accept)
        self.accept_btn.setVisible(False)
        close = pill_button("Fechar", "red")
        close.clicked.connect(self.reject)
        buttons.addWidget(self.accept_btn)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self.view_combo.currentIndexChanged.connect(self._changed)
        self.undo_spin.valueChanged.connect(self._changed)
        self.press_spin.valueChanged.connect(self._changed)

    @staticmethod
    def _panel(layout: QVBoxLayout) -> QFrame:
        panel = QFrame()
        panel.setObjectName("ss4_panel")
        layout.addWidget(panel)
        return panel

    def _changed(self, *_args) -> None:
        self.accept_btn.setVisible(True)

    def default_view(self) -> str:
        return str(self.view_combo.currentData())

    def undo_limit(self) -> int:
        return int(self.undo_spin.value())

    def press_size(self) -> int:
        return int(self.press_spin.value())
