from __future__ import annotations

import time
from enum import Enum

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
)

from packages.image.conversion import pil_to_qpixmap


class CanvasTool(str, Enum):
    MOVE = "move"
    SELECT = "select"  # seleção retangular (SS4: Select Area)
    LASSO = "lasso"
    POLY_LASSO = "poly_lasso"
    SATURATE = "saturate"  # SS4: gota
    DESATURATE = "desaturate"  # SS4: esponja
    ERASER = "eraser"
    ZOOM = "zoom"


# Nomes antigos das ferramentas de pintura.
_TOOL_SYNONYMS = {"dropper": CanvasTool.SATURATE, "sponge": CanvasTool.DESATURATE}

ZOOM_TOOL_STEP = 1.25
DEFAULT_BRUSH_DIAMETER = 32
MAX_BRUSH_DIAMETER = 500
DEFAULT_FEATHER = 2
_POLY_CLOSE_DISTANCE_PX = 8
_BRUSH_TOOLS = (CanvasTool.SATURATE, CanvasTool.DESATURATE, CanvasTool.ERASER)


def feather_mask(mask: np.ndarray, feather: float) -> np.ndarray:
    """Seleção 0..1 com a borda suavizada em ``feather`` px (0 = borda dura)."""
    out = np.asarray(mask, dtype=np.float32)
    if feather <= 0 or not out.any():
        return out.copy()
    sigma = float(feather) / 2.0
    return np.clip(cv2.GaussianBlur(out, (0, 0), sigmaX=sigma, sigmaY=sigma), 0.0, 1.0).astype(np.float32)


def _zoom_cursor() -> QCursor:
    """Cursor de lupa para a ferramenta Zoom."""
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    for color, width in ((Qt.GlobalColor.white, 4), (Qt.GlobalColor.black, 2)):
        painter.setPen(QPen(color, width))
        painter.drawEllipse(2, 2, 13, 13)
        painter.drawLine(14, 14, 21, 21)
    painter.end()
    return QCursor(pixmap, 8, 8)


def _selection_pen() -> QPen:
    pen = QPen(Qt.GlobalColor.yellow, 2, Qt.PenStyle.DashLine)
    pen.setCosmetic(True)
    return pen


def _mask_outline(mask: np.ndarray) -> QPainterPath:
    """Contorno (formigas) de uma seleção por máscara."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    for contour in contours:
        pts = contour.reshape(-1, 2)
        if len(pts) < 2:
            continue
        path.addPolygon(QPolygonF([QPointF(float(x), float(y)) for x, y in pts]))
        path.closeSubpath()
    return path


class ImageCanvasView(QGraphicsView):
    """Interactive canvas with zoom, pan and selection."""

    selection_changed = Signal(list)
    eraser_stroke = Signal(int, int)
    clicked = Signal(int, int)
    pixel_probed = Signal(int, int)
    # Traço de pincel (Saturate/Desaturate/Eraser): ferramenta, x, y (imagem), Alt pressionado.
    brush_pressed = Signal(str, float, float, bool)
    brush_moved = Signal(float, float)
    brush_released = Signal()
    brush_diameter_changed = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._selection_item: QGraphicsRectItem | QGraphicsPathItem | None = None
        # Seleção que não é geometria simples (cor, inversa): máscara booleana da imagem.
        self._selection_mask: np.ndarray | None = None
        self._brush_cursor: QGraphicsEllipseItem | None = None
        self._brushing = False
        self._tool = CanvasTool.MOVE
        self._zoom = 1.0
        self._panning = False
        self._selecting = False
        self._lassoing = False
        self._lasso_points: list[QPointF] = []
        self._poly_points: list[QPointF] = []
        self._start_pos: QPointF | None = None
        self._brush_diameter = DEFAULT_BRUSH_DIAMETER
        self._feather = DEFAULT_FEATHER
        self._last_probe_emit = 0.0
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#808080"))

    def set_tool(self, tool: CanvasTool | str) -> None:
        if not isinstance(tool, CanvasTool):
            tool = _TOOL_SYNONYMS.get(str(tool)) or CanvasTool(tool)
        if tool != CanvasTool.POLY_LASSO and self._poly_points:
            self._cancel_poly()
        self._tool = tool
        if tool == CanvasTool.MOVE:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif tool in (CanvasTool.SELECT, CanvasTool.LASSO, CanvasTool.POLY_LASSO):
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif tool in _BRUSH_TOOLS:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif tool == CanvasTool.ZOOM:
            self.setCursor(_zoom_cursor())
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        if tool not in _BRUSH_TOOLS and self._brush_cursor is not None:
            self._brush_cursor.hide()

    @property
    def tool(self) -> CanvasTool:
        return self._tool

    def set_brush_diameter(self, diameter: int) -> None:
        diameter = int(min(MAX_BRUSH_DIAMETER, max(1, diameter)))
        if diameter == self._brush_diameter:
            return
        self._brush_diameter = diameter
        self.brush_diameter_changed.emit(diameter)

    @property
    def brush_diameter(self) -> int:
        return self._brush_diameter

    def set_feather(self, feather: float) -> None:
        """Feather das seleções em px (vale para a seleção atual e as próximas)."""
        self._feather = max(0.0, float(feather))

    @property
    def feather(self) -> float:
        return self._feather

    def _show_brush_cursor(self, scene_pos: QPointF) -> None:
        if self._pixmap_item is None:
            return
        if self._brush_cursor is None:
            pen = QPen(Qt.GlobalColor.white, 1, Qt.PenStyle.DotLine)
            pen.setCosmetic(True)
            self._brush_cursor = QGraphicsEllipseItem()
            self._brush_cursor.setPen(pen)
            self._brush_cursor.setZValue(20)
            self._scene.addItem(self._brush_cursor)
        r = self._brush_diameter / 2.0
        self._brush_cursor.setRect(scene_pos.x() - r, scene_pos.y() - r, 2 * r, 2 * r)
        self._brush_cursor.show()

    def set_image_from_pil(self, image, *, fit: bool = True) -> None:
        self._scene.clear()
        self._pixmap_item = None
        self._selection_item = None
        self._selection_mask = None
        self._brush_cursor = None
        self._poly_points = []
        self._lasso_points = []
        if image is None:
            return
        pixmap = pil_to_qpixmap(image)
        self._pixmap_item = QGraphicsPixmapItem(pixmap)
        self._scene.addItem(self._pixmap_item)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        if fit:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = 1.0

    def update_image_from_pil(self, image, *, fast: bool = False) -> None:
        """Atualiza pixmap sem resetar zoom/seleção — uso em preview ao vivo."""
        if image is None:
            self.set_image_from_pil(None)
            return
        was_smooth = self.renderHints() & QPainter.RenderHint.SmoothPixmapTransform
        if fast and was_smooth:
            self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        pixmap = pil_to_qpixmap(image)
        if fast and was_smooth:
            self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self._pixmap_item is None:
            self.set_image_from_pil(image)
            return
        self._pixmap_item.setPixmap(pixmap)
        new_rect = self._pixmap_item.boundingRect()
        if self._scene.sceneRect() != new_rect:
            self._scene.setSceneRect(new_rect)

    def has_image(self) -> bool:
        return self._pixmap_item is not None

    # ------------------------------------------------------------ zoom
    def zoom_in(self) -> None:
        self._apply_zoom(1.25)

    def zoom_out(self) -> None:
        self._apply_zoom(0.8)

    def _apply_zoom(self, factor: float) -> None:
        self._zoom *= factor
        self.scale(factor, factor)

    def zoom_at(self, scene_pos: QPointF, factor: float) -> None:
        """Aplica o zoom e centraliza a vista no ponto clicado (ferramenta Zoom)."""
        self._apply_zoom(factor)
        self.centerOn(scene_pos)

    def fit_to_window(self) -> None:
        """Fit on Screen: imagem inteira visível."""
        if self._pixmap_item is None:
            return
        self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()

    def fill_window(self) -> None:
        """Zoom Fill Window: a imagem preenche a janela (pode cortar um dos lados)."""
        if self._pixmap_item is None:
            return
        self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatioByExpanding)
        self._zoom = self.transform().m11()

    def actual_pixels(self) -> None:
        """Actual Pixels: 100% (1 pixel da imagem = 1 pixel da tela)."""
        center = self.mapToScene(self.viewport().rect().center())
        self.resetTransform()
        self._zoom = 1.0
        self.centerOn(center)

    # ------------------------------------------------------------ seleção
    def image_shape(self) -> tuple[int, int] | None:
        """(altura, largura) da imagem exibida."""
        if self._pixmap_item is None:
            return None
        r = self._pixmap_item.boundingRect()
        return int(r.height()), int(r.width())

    def get_selection_bbox(self) -> list[int] | None:
        if self._selection_item is None or self._pixmap_item is None:
            return None
        if self._selection_mask is not None:
            ys, xs = np.nonzero(self._selection_mask)
            if len(xs) == 0:
                return None
            return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
        if isinstance(self._selection_item, QGraphicsRectItem):
            rect = self._selection_item.rect()
        else:
            rect = self._selection_item.path().boundingRect()
        return [int(rect.left()), int(rect.top()), int(rect.right()), int(rect.bottom())]

    def get_selection_polygon(self) -> list[tuple[float, float]] | None:
        """Contorno da seleção em coordenadas da imagem (retângulo, laço ou polígono)."""
        if self._selection_item is None:
            return None
        if isinstance(self._selection_item, QGraphicsRectItem):
            r = self._selection_item.rect()
            return [(r.left(), r.top()), (r.right(), r.top()), (r.right(), r.bottom()), (r.left(), r.bottom())]
        polygon = self._selection_item.path().toFillPolygon()
        return [(p.x(), p.y()) for p in polygon]

    def has_selection(self) -> bool:
        return self._selection_item is not None

    def selection_mask(self, shape: tuple[int, int] | None = None) -> np.ndarray | None:
        """Seleção atual como máscara booleana (altura × largura); None sem seleção."""
        if self._selection_item is None or self._pixmap_item is None or self._poly_points:
            return None
        shape = shape or self.image_shape()
        if shape is None:
            return None
        h, w = shape
        if self._selection_mask is not None:
            mask = self._selection_mask
            if mask.shape != (h, w):
                mask = cv2.resize(mask.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
            return mask.copy()
        out = np.zeros((h, w), dtype=np.uint8)
        if isinstance(self._selection_item, QGraphicsRectItem):
            r = self._selection_item.rect()
            x0, y0 = max(0, int(round(r.left()))), max(0, int(round(r.top())))
            x1, y1 = min(w, int(round(r.right()))), min(h, int(round(r.bottom())))
            out[y0:y1, x0:x1] = 1
        else:
            pts = self.get_selection_polygon() or []
            if len(pts) >= 3:
                poly = np.round(np.asarray(pts, dtype=np.float64)).astype(np.int32).reshape(-1, 1, 2)
                cv2.fillPoly(out, [poly], 1)
        return out.astype(bool)

    def get_selection_mask(self, shape: tuple[int, int] | None = None) -> np.ndarray | None:
        """Seleção como máscara float32 0..1 com o Feather aplicado; None sem seleção."""
        mask = self.selection_mask(shape)
        if mask is None:
            return None
        return feather_mask(mask, self._feather)

    def set_selection_mask(self, mask: np.ndarray | None) -> None:
        """Seleção por máscara (Inverse Selection); máscara vazia limpa a seleção."""
        if mask is None or self._pixmap_item is None or not np.asarray(mask).any():
            self.clear_selection()
            return
        self._cancel_poly()
        mask = np.asarray(mask, dtype=bool)
        self._replace_selection_item(QGraphicsPathItem(_mask_outline(mask)))
        self._selection_mask = mask.copy()
        bbox = self.get_selection_bbox()
        if bbox:
            self.selection_changed.emit(bbox)

    def invert_selection(self) -> bool:
        """Edit > Inverse Selection: imagem inteira menos a seleção atual."""
        mask = self.selection_mask()
        if mask is None:
            return False
        self.set_selection_mask(~mask)
        return True

    def clear_selection(self) -> None:
        self._cancel_poly()
        self._selection_mask = None
        if self._selection_item is not None:
            self._scene.removeItem(self._selection_item)
            self._selection_item = None
            self.selection_changed.emit([])

    def _replace_selection_item(self, item) -> None:
        self._selection_mask = None
        if self._selection_item is not None:
            self._scene.removeItem(self._selection_item)
        self._selection_item = item
        if item is not None:
            item.setPen(_selection_pen())
            item.setZValue(10)
            self._scene.addItem(item)

    def _path_item(self, points: list[QPointF], *, closed: bool) -> QGraphicsPathItem:
        path = QPainterPath()
        if points:
            path.addPolygon(QPolygonF(points))
            if closed:
                path.closeSubpath()
        return QGraphicsPathItem(path)

    def _finish_polygon_selection(self, points: list[QPointF]) -> None:
        if len(points) < 3:
            self._replace_selection_item(None)
            return
        self._replace_selection_item(self._path_item(points, closed=True))
        bbox = self.get_selection_bbox()
        if bbox and bbox[2] > bbox[0] and bbox[3] > bbox[1]:
            self.selection_changed.emit(bbox)

    def _cancel_poly(self) -> None:
        if self._poly_points:
            self._poly_points = []
            if isinstance(self._selection_item, QGraphicsPathItem):
                self._replace_selection_item(None)

    def _clamp_to_image(self, pos: QPointF) -> QPointF:
        if self._pixmap_item is None:
            return pos
        r: QRectF = self._pixmap_item.boundingRect()
        return QPointF(min(max(pos.x(), r.left()), r.right()), min(max(pos.y(), r.top()), r.bottom()))

    # ------------------------------------------------------------ eventos
    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._pixmap_item is None:
            event.ignore()
            return
        scene_pos = self.mapToScene(event.position().toPoint())
        if not self._pixmap_item.contains(scene_pos):
            event.ignore()
            return
        old_anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom *= factor
        self.scale(factor, factor)
        self.setTransformationAnchor(old_anchor)
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._pixmap_item is None:
            super().mousePressEvent(event)
            return
        scene_pos = self.mapToScene(event.position().toPoint())
        left = event.button() == Qt.MouseButton.LeftButton
        if self._tool == CanvasTool.ZOOM and event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
        ):
            zoom_out = event.button() == Qt.MouseButton.RightButton or bool(
                event.modifiers() & Qt.KeyboardModifier.AltModifier
            )
            self.zoom_at(scene_pos, 1 / ZOOM_TOOL_STEP if zoom_out else ZOOM_TOOL_STEP)
            event.accept()
            return
        if self._tool == CanvasTool.MOVE and left:
            self._panning = True
            self._start_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self._tool == CanvasTool.SELECT and left:
            self._selecting = True
            self._start_pos = scene_pos
            self._replace_selection_item(QGraphicsRectItem())
        elif self._tool == CanvasTool.LASSO and left:
            self._lassoing = True
            self._lasso_points = [self._clamp_to_image(scene_pos)]
            self._replace_selection_item(self._path_item(self._lasso_points, closed=False))
        elif self._tool == CanvasTool.POLY_LASSO and left:
            self._add_poly_point(self._clamp_to_image(scene_pos))
            event.accept()
            return
        elif self._tool in _BRUSH_TOOLS and left:
            self._brushing = True
            alt = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            self._show_brush_cursor(scene_pos)
            self.brush_pressed.emit(self._tool.value, scene_pos.x(), scene_pos.y(), alt)
            if self._tool == CanvasTool.ERASER:
                self.eraser_stroke.emit(int(scene_pos.x()), int(scene_pos.y()))
            event.accept()
            return
        super().mousePressEvent(event)

    def _add_poly_point(self, point: QPointF) -> None:
        if len(self._poly_points) >= 3:
            first = self.mapFromScene(self._poly_points[0])
            here = self.mapFromScene(point)
            if (first - here).manhattanLength() <= _POLY_CLOSE_DISTANCE_PX:
                self._close_poly()
                return
        self._poly_points.append(point)
        self._replace_selection_item(self._path_item(self._poly_points, closed=False))

    def _close_poly(self) -> None:
        points, self._poly_points = self._poly_points, []
        self._finish_polygon_selection(points)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._tool == CanvasTool.POLY_LASSO and self._poly_points:
            self._close_poly()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        if self._tool == CanvasTool.POLY_LASSO and self._poly_points:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._close_poly()
                return
            if event.key() == Qt.Key.Key_Escape:
                self._cancel_poly()
                return
        if self._tool in _BRUSH_TOOLS and event.key() in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight):
            step = max(1, self._brush_diameter // 5)
            grow = event.key() == Qt.Key.Key_BracketRight
            self.set_brush_diameter(self._brush_diameter + step if grow else self._brush_diameter - step)
            if self._brush_cursor is not None and self._brush_cursor.isVisible():
                self._show_brush_cursor(self._brush_cursor.rect().center())
            return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning and self._start_pos is not None:
            delta = event.position() - self._start_pos
            self._start_pos = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
        elif self._selecting and self._start_pos is not None and isinstance(
            self._selection_item, QGraphicsRectItem
        ):
            scene_pos = self.mapToScene(event.position().toPoint())
            x0, y0 = self._start_pos.x(), self._start_pos.y()
            x1, y1 = scene_pos.x(), scene_pos.y()
            self._selection_item.setRect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        elif self._lassoing and isinstance(self._selection_item, QGraphicsPathItem):
            scene_pos = self._clamp_to_image(self.mapToScene(event.position().toPoint()))
            self._lasso_points.append(scene_pos)
            path = self._selection_item.path()
            path.lineTo(scene_pos)
            self._selection_item.setPath(path)
        elif self._tool in _BRUSH_TOOLS:
            scene_pos = self.mapToScene(event.position().toPoint())
            self._show_brush_cursor(scene_pos)
            if self._brushing:
                self.brush_moved.emit(scene_pos.x(), scene_pos.y())
                if self._tool == CanvasTool.ERASER:
                    self.eraser_stroke.emit(int(scene_pos.x()), int(scene_pos.y()))
        if (
            self._pixmap_item is not None
            and not self._panning
            and not self._selecting
            and not self._lassoing
        ):
            scene_pos = self.mapToScene(event.position().toPoint())
            if self._pixmap_item.contains(scene_pos):
                now = time.monotonic()
                if now - self._last_probe_emit >= 0.05:
                    self._last_probe_emit = now
                    self.pixel_probed.emit(int(scene_pos.x()), int(scene_pos.y()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            self._panning = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        if self._selecting:
            self._selecting = False
            bbox = self.get_selection_bbox()
            if bbox and bbox[2] > bbox[0] and bbox[3] > bbox[1]:
                self.selection_changed.emit(bbox)
        if self._lassoing:
            self._lassoing = False
            points, self._lasso_points = self._lasso_points, []
            self._finish_polygon_selection(points)
        if self._brushing:
            self._brushing = False
            self.brush_released.emit()
        super().mouseReleaseEvent(event)
