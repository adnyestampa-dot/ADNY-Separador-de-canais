"""Ícones usados na versão Clean (lixeira e checkbox de tinta na barra de canais)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QPolygonF


def _canvas(size: int) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pixmap, painter


def trash_pixmap(size: int = 40, *, hot: bool = False) -> QPixmap:
    pixmap, p = _canvas(size)
    color = QColor("#f14c4c") if hot else QColor("#d8d8d8")
    s = size / 40.0
    p.setPen(QPen(color.darker(160), 1.2 * s))
    p.setBrush(QBrush(color))
    p.drawRoundedRect(QRectF(9 * s, 4 * s, 22 * s, 4 * s), 1.5 * s, 1.5 * s)
    p.drawRect(QRectF(16 * s, 1.5 * s, 8 * s, 3 * s))
    body = QPolygonF(
        [QPointF(10 * s, 10 * s), QPointF(30 * s, 10 * s), QPointF(28 * s, 38 * s), QPointF(12 * s, 38 * s)]
    )
    p.drawPolygon(body)
    p.setPen(QPen(color.darker(170), 1.6 * s))
    for x in (15.5, 20, 24.5):
        p.drawLine(QPointF(x * s, 14 * s), QPointF(x * s, 34 * s))
    p.end()
    return pixmap


def ink_check_pixmap(rgb: tuple[int, int, int], checked: bool, size: int = 16) -> QPixmap:
    pixmap, p = _canvas(size)
    fill = QColor(*rgb)
    p.setPen(QPen(QColor("#bfbfbf"), 1))
    p.setBrush(QBrush(fill))
    p.drawRect(QRectF(0.5, 0.5, size - 1, size - 1))
    if checked:
        light = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) > 170
        p.setPen(QPen(QColor("#111") if light else QColor("#fff"), max(1.6, size / 9)))
        p.drawPolyline(
            QPolygonF(
                [
                    QPointF(size * 0.22, size * 0.52),
                    QPointF(size * 0.42, size * 0.74),
                    QPointF(size * 0.80, size * 0.26),
                ]
            )
        )
    p.end()
    return pixmap
