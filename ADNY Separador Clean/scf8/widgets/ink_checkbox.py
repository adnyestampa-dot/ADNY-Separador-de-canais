from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QCheckBox, QWidget

from scf8.ui.ss4_icons import ink_check_pixmap

_BOX = 18


class InkCheckBox(QCheckBox):
    """Checkbox quadrado na cor da tinta (barra 'Active Separations' do SS4)."""

    def __init__(
        self, channel_id: str, rgb: tuple[int, int, int], tooltip: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.channel_id = channel_id
        self._rgb = tuple(int(c) for c in rgb)
        self.setToolTip(tooltip)
        self.setFixedSize(QSize(_BOX + 2, _BOX + 2))

    @property
    def ink_rgb(self) -> tuple[int, int, int]:
        return self._rgb  # type: ignore[return-value]

    def set_ink_rgb(self, rgb: tuple[int, int, int]) -> None:
        self._rgb = tuple(int(c) for c in rgb)
        self.update()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.drawPixmap(1, 1, ink_check_pixmap(self._rgb, self.isChecked(), _BOX))  # type: ignore[arg-type]
        painter.end()
