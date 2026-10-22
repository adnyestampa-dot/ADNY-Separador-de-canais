from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from apps.desktop_qt.canvases.image_view import CanvasTool, ImageCanvasView
from scf8.branding import NO_DOCUMENT_TITLE

class VueRiteWidget(QWidget):
    """Canvas VueRite da janela «arquivo : prova positiva»."""

    result_pixel_probed = Signal(int, int)
    selection_changed = Signal(list)
    eraser_stroke = Signal(int, int)
    brush_pressed = Signal(str, float, float, bool)
    brush_moved = Signal(float, float)
    brush_released = Signal()
    brush_diameter_changed = Signal(int)
    # Imagem exibida mudou (composite/original) — alimenta a miniatura 'Proof Positive'.
    display_image_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view = ImageCanvasView()
        self._view.setBackgroundBrush(QColor("#3c3c3c"))
        self._view.pixel_probed.connect(self.result_pixel_probed.emit)
        self._view.selection_changed.connect(self.selection_changed.emit)
        self._view.eraser_stroke.connect(self.eraser_stroke.emit)
        self._view.brush_pressed.connect(self.brush_pressed.emit)
        self._view.brush_moved.connect(self.brush_moved.emit)
        self._view.brush_released.connect(self.brush_released.emit)
        self._view.brush_diameter_changed.connect(self.brush_diameter_changed.emit)
        self._original_image = None
        self._result_image = None

        self.header = QLabel(NO_DOCUMENT_TITLE)
        self.header.setObjectName("vueRiteTitle")
        self.header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.header.setStyleSheet(
            "color: #1a1a1a; background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 #c9daf0, stop:1 #a8c0e0); padding: 3px 8px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self._view, stretch=1)

    @property
    def active_view(self) -> ImageCanvasView:
        return self._view

    def views(self) -> list[ImageCanvasView]:
        """Vistas deste VueRite (as janelas extras ficam na DocumentArea)."""
        return [self._view]

    def set_title(self, title: str | None) -> None:
        self.header.setText(title or NO_DOCUMENT_TITLE)

    def title(self) -> str:
        return self.header.text()

    def set_left_panel_title(self, _title: str) -> None:
        pass

    def set_original_from_pil(self, image) -> None:
        self._original_image = image
        if self._result_image is None:
            self._view.set_image_from_pil(image)
            self.display_image_changed.emit(image)

    def set_result_from_pil(self, image) -> None:
        self._result_image = image
        self._view.set_image_from_pil(image)
        self.display_image_changed.emit(image if image is not None else self._original_image)

    def update_result_from_pil(self, image, *, fast: bool = False) -> None:
        self._result_image = image
        self._view.update_image_from_pil(image, fast=fast)
        self.display_image_changed.emit(image)

    def has_result_image(self) -> bool:
        return self._result_image is not None

    def display_image(self):
        """Imagem exibida: o composite (Proof Positive) ou, antes da separação, o original."""
        return self._result_image if self._result_image is not None else self._original_image

    def set_tool(self, tool: CanvasTool | str) -> None:
        self._view.set_tool(tool)

    def zoom_in(self) -> None:
        self._view.zoom_in()

    def zoom_out(self) -> None:
        self._view.zoom_out()

    def fit_to_window(self) -> None:
        self._view.fit_to_window()

    def fill_window(self) -> None:
        self._view.fill_window()

    def actual_pixels(self) -> None:
        self._view.actual_pixels()

    def set_brush_diameter(self, diameter: int) -> None:
        self._view.set_brush_diameter(diameter)

    @property
    def brush_diameter(self) -> int:
        return self._view.brush_diameter

    def set_feather(self, feather: float) -> None:
        self._view.set_feather(feather)

    def get_selection_mask(self, shape: tuple[int, int] | None = None):
        """Seleção float32 0..1 (altura × largura da imagem) com Feather; None sem seleção."""
        return self._view.get_selection_mask(shape)

    def get_selection_bbox(self) -> list[int] | None:
        return self._view.get_selection_bbox()

    def get_selection_polygon(self) -> list[tuple[float, float]] | None:
        return self._view.get_selection_polygon()

    def has_selection(self) -> bool:
        return self._view.has_selection()

    def selection_mask(self, shape: tuple[int, int] | None = None):
        return self._view.selection_mask(shape)

    def set_selection_mask(self, mask) -> None:
        self._view.set_selection_mask(mask)

    def invert_selection(self) -> bool:
        return self._view.invert_selection()

    def clear_selection(self) -> None:
        self._view.clear_selection()
