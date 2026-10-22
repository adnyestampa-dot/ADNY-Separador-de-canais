from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

if TYPE_CHECKING:
    from scf8.presenters.scf8_presenter import Scf8Presenter


class PrintCommanderDialog(QDialog):
    """Janela de impressão (paridade Print Commander SS4 — clean-room)."""

    def __init__(self, parent, presenter: Scf8Presenter) -> None:
        super().__init__(parent)
        self._presenter = presenter
        self.setWindowTitle("Comandante de impressão")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Configure separações, marcas e saída para filme/RIP. "
            "Use 「Exportar filmes PDF」 para abrir o assistente FAV8+ completo."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        sep_box = QGroupBox("Separações")
        sep_form = QFormLayout(sep_box)
        channels = presenter.project_state.channels
        if channels:
            for ch in channels:
                sep_form.addRow(ch.name or ch.id, QLabel("LPI / ângulo — pré-impressão FAV8+"))
        else:
            sep_form.addRow(QLabel("Nenhum canal — execute Separar Spot Process primeiro."))
        layout.addWidget(sep_box)

        marks_box = QGroupBox("Marcas e tamanho")
        marks_layout = QVBoxLayout(marks_box)
        marks_layout.addWidget(QLabel("Registro, centerline e nesting: assistente de exportação PDF."))
        layout.addWidget(marks_box)

        export_btn = QPushButton("Exportar filmes PDF…")
        export_btn.clicked.connect(self._export)
        layout.addWidget(export_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Fechar")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _export(self) -> None:
        self._presenter.export_films_from_commander()
