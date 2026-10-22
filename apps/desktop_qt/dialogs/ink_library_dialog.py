"""Editor da biblioteca de tintas usada nas próximas separações."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from packages.core.services.ink_library_service import InkLibraryService
from packages.skills.fav8_plus.ink_library import InkDefinition, InkLibrarySnapshot

_HEADERS = ("ID", "Nome", "L*", "a*", "b*", "R", "G", "B", "Role")


class InkLibraryDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        service: InkLibraryService | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Biblioteca de tintas")
        self.resize(1050, 620)
        self._service = service or InkLibraryService()
        self._snapshot = self._service.load()

        layout = QVBoxLayout(self)
        explanation = QLabel(
            "<b>Referência Lab para matching</b> — usada para escolher e distribuir "
            "canais. Não representa calibração física. O RGB é somente a cor de preview."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        for label, callback in (
            ("Adicionar", self._add),
            ("Remover", self._remove),
            ("Importar…", self._import),
            ("Exportar…", self._export),
            ("Restaurar padrões", self._reset),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "Salvar para a próxima separação"
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._populate(self._snapshot)

    def _populate(self, snapshot: InkLibrarySnapshot) -> None:
        self.table.setRowCount(0)
        for ink in snapshot.inks:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (
                ink.id,
                ink.nome,
                *(f"{value:.6f}" for value in ink.lab_reference),
                *(str(value) for value in ink.display_rgb),
                ink.role,
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))

    def _add(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = (
            f"user:ink_{row + 1}",
            "Nova tinta",
            "50",
            "0",
            "0",
            "128",
            "128",
            "128",
            "chromatic",
        )
        for column, value in enumerate(values):
            self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.setCurrentCell(row, 1)
        self.table.editItem(self.table.item(row, 1))

    def _remove(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar biblioteca", "", "Biblioteca JSON (*.json)"
        )
        if not path:
            return
        try:
            self._snapshot = self._service.import_file(path)
            self._populate(self._snapshot)
        except (OSError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Importação inválida", str(exc))

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar biblioteca", "ink_library.json", "Biblioteca JSON (*.json)"
        )
        if not path:
            return
        try:
            snapshot = self._snapshot_from_table()
            InkLibraryService(Path(path)).save(snapshot)
        except (OSError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Não foi possível exportar", str(exc))

    def _reset(self) -> None:
        self._snapshot = self._service.reset()
        self._populate(self._snapshot)

    def _snapshot_from_table(self) -> InkLibrarySnapshot:
        inks = []
        previous = {ink.id: ink for ink in self._snapshot.inks}
        for row in range(self.table.rowCount()):
            values = [
                self.table.item(row, column).text().strip()
                if self.table.item(row, column) is not None
                else ""
                for column in range(len(_HEADERS))
            ]
            metadata = previous.get(values[0]).metadados if values[0] in previous else {}
            inks.append(
                InkDefinition(
                    id=values[0],
                    nome=values[1],
                    lab_reference=(float(values[2]), float(values[3]), float(values[4])),
                    display_rgb=(float(values[5]), float(values[6]), float(values[7])),
                    role=values[8],
                    metadados=metadata,
                )
            )
        version = f"user-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')}"
        return InkLibrarySnapshot(version=version, inks=tuple(inks))

    def accept(self) -> None:
        try:
            self._snapshot = self._service.save(self._snapshot_from_table())
        except (OSError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Biblioteca inválida", str(exc))
            return
        super().accept()
