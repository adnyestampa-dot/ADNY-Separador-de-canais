from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QWidget

from apps.desktop_qt.widgets.channel_item import MIME_TYPE
from scf8.ui.ss4_icons import trash_pixmap


class Ss4TrashCan(QLabel):
    """Lixeira à direita da barra de separações: fica vermelha com uma separação por cima; soltar exclui."""

    delete_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ss4Trash")
        self.setAcceptDrops(True)
        self.setFixedSize(48, 56)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setToolTip("Arraste uma separação aqui para excluir (Desfazer restaura)")
        self._hot = False
        self._set_hot(False)

    def is_hot(self) -> bool:
        return self._hot

    def _set_hot(self, hot: bool) -> None:
        self._hot = hot
        self.setProperty("hot", hot)
        self.setPixmap(trash_pixmap(40, hot=hot))
        self.setStyleSheet("QLabel#ss4Trash { background: rgba(224, 42, 42, 90); border-radius: 6px; }" if hot else "")

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_TYPE):
            self._set_hot(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_hot(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._set_hot(False)
        if not event.mimeData().hasFormat(MIME_TYPE):
            return
        channel_id = bytes(event.mimeData().data(MIME_TYPE)).decode()
        event.acceptProposedAction()
        if channel_id:
            self.delete_requested.emit(channel_id)
