from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

_SIZE = 32
_WHITE = QColor("#f2f2f2")


def _canvas(size: int = _SIZE) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pixmap, painter


def _arrow_head(p: QPainter, tip: QPointF, dx: float, dy: float, size: float = 4.5) -> None:
    nx, ny = -dy, dx
    base = QPointF(tip.x() - dx * size, tip.y() - dy * size)
    p.drawPolygon(
        QPolygonF(
            [
                tip,
                QPointF(base.x() + nx * size * 0.8, base.y() + ny * size * 0.8),
                QPointF(base.x() - nx * size * 0.8, base.y() - ny * size * 0.8),
            ]
        )
    )


def _draw_move(p: QPainter) -> None:
    c = _SIZE / 2
    p.setPen(QPen(_WHITE, 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(4, c), QPointF(_SIZE - 4, c))
    p.drawLine(QPointF(c, 4), QPointF(c, _SIZE - 4))
    p.drawEllipse(QPointF(c, c), 3.5, 3.5)
    p.setBrush(QBrush(_WHITE))
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        _arrow_head(p, QPointF(c + dx * 13, c + dy * 13), dx, dy)


def _draw_zoom(p: QPainter) -> None:
    p.setPen(QPen(_WHITE, 2.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(13, 13), 9, 9)
    p.drawLine(QPointF(10, 13), QPointF(16, 13))
    p.drawLine(QPointF(13, 10), QPointF(13, 16))
    p.setPen(QPen(_WHITE, 4.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(20, 20), QPointF(28, 28))


def _dashed() -> QPen:
    return QPen(_WHITE, 1.4, Qt.PenStyle.DashLine)


def _draw_lasso(p: QPainter) -> None:
    p.setPen(_dashed())
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(6, 18))
    path.cubicTo(QPointF(2, 6), QPointF(20, 2), QPointF(26, 10))
    path.cubicTo(QPointF(31, 18), QPointF(22, 26), QPointF(14, 21))
    path.cubicTo(QPointF(10, 19), QPointF(9, 23), QPointF(6, 18))
    p.drawPath(path)


def _draw_poly_lasso(p: QPainter) -> None:
    p.setPen(_dashed())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolygon(
        QPolygonF([QPointF(4, 26), QPointF(9, 9), QPointF(16, 13), QPointF(24, 5), QPointF(28, 24)])
    )


def _draw_rect_select(p: QPainter) -> None:
    p.setPen(_dashed())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(5, 7, 22, 18))


def _draw_dropper(p: QPainter) -> None:
    path = QPainterPath(QPointF(16, 4))
    path.cubicTo(QPointF(20, 11), QPointF(26, 16), QPointF(26, 21))
    path.arcTo(QRectF(6, 11, 20, 18), 0, -180)
    path.cubicTo(QPointF(6, 16), QPointF(12, 11), QPointF(16, 4))
    p.setPen(QPen(_WHITE, 1.6))
    p.setBrush(QBrush(QColor("#3a3a3a")))
    p.drawPath(path)
    p.setPen(QPen(_WHITE, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(QRectF(10, 15, 10, 10), 200 * 16, 70 * 16)


def _draw_sponge(p: QPainter) -> None:
    p.save()
    p.translate(16, 17)
    p.rotate(-18)
    p.setPen(QPen(QColor("#8a6d00"), 1.2))
    p.setBrush(QBrush(QColor("#f2c418")))
    p.drawRoundedRect(QRectF(-12, -8, 24, 16), 4, 4)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#b58e00")))
    for x, y in ((-7, -3), (-2, 2), (4, -4), (7, 3), (-6, 4), (1, -1)):
        p.drawEllipse(QPointF(x, y), 1.3, 1.3)
    p.restore()


def _draw_eraser(p: QPainter) -> None:
    p.save()
    p.translate(16, 16)
    p.rotate(-40)
    p.setPen(QPen(QColor("#5a1010"), 1.0))
    p.setBrush(QBrush(QColor("#e8473a")))
    p.drawRoundedRect(QRectF(-4, -6, 16, 12), 2, 2)
    p.setBrush(QBrush(QColor("#d9d9d9")))
    p.drawRect(QRectF(-9, -6, 5, 12))
    p.setBrush(QBrush(QColor("#f4a6b0")))
    p.drawRoundedRect(QRectF(-14, -6, 5, 12), 2, 2)
    p.restore()


_TOOL_PAINTERS = {
    "tool.move": _draw_move,
    "tool.zoom": _draw_zoom,
    "tool.lasso": _draw_lasso,
    "tool.poly_lasso": _draw_poly_lasso,
    "tool.rect_select": _draw_rect_select,
    "tool.saturate": _draw_dropper,
    "tool.desaturate": _draw_sponge,
    "tool.eraser": _draw_eraser,
}


def tool_icon(action_id: str) -> QIcon | None:
    painter_fn = _TOOL_PAINTERS.get(action_id)
    if painter_fn is None:
        return None
    pixmap, painter = _canvas()
    painter_fn(painter)
    painter.end()
    return QIcon(pixmap)


def drag_pixmap(size: int = 24) -> QPixmap:
    pixmap, painter = _canvas(_SIZE)
    _draw_move(painter)
    painter.end()
    return pixmap.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )


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
    """Quadrado na cor da tinta com visto branco (checkbox 'Active Separations')."""
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

