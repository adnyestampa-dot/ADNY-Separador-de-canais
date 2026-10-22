from __future__ import annotations

from typing import Callable

import numpy as np
from PIL import Image
from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMdiArea, QMdiSubWindow

from apps.desktop_qt.canvases.image_view import CanvasTool, ImageCanvasView
from scf8.branding import GENERATED_VIEW_TITLE, NO_DOCUMENT_TITLE, ORIGINAL_VIEW_TITLE
from scf8.ui.vuerite_widget import VueRiteWidget

# Vista composite (imagem gerada); original = arte enviada; demais = id da separação.
PROOF_VIEW = "proof"
ORIGINAL_VIEW = "original"
_REFRESH_DEBOUNCE_MS = 200
_NAVIGATION_TOOLS = (CanvasTool.MOVE, CanvasTool.ZOOM)

# kind → (título, imagem); None = a vista não existe mais (a janela é fechada).
ViewRenderer = Callable[[str], "tuple[str, Image.Image] | None"]


def separation_plate(mask: np.ndarray, ink_rgb: tuple[int, int, int] | None) -> Image.Image:
    """Chapa em tamanho real: tinta sobre preto (Film View, ``ink_rgb=None``: preto sobre branco)."""
    values = np.asarray(mask)
    if values.dtype != np.uint8:
        values = values.astype(np.float32, copy=False)
        if values.size and values.max() > 1.0:
            values = values / 255.0
        values = (np.clip(values, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    if ink_rgb is None:
        return Image.fromarray(255 - values, mode="L").convert("RGB")
    ink = np.asarray(ink_rgb, dtype=np.uint16)
    rgb = (values[..., None].astype(np.uint16) * ink + 127) // 255
    return Image.fromarray(rgb.astype(np.uint8), mode="RGB")


class _DocumentSubWindow(QMdiSubWindow):
    """Sub-janela principal (VueRite): fechá-la fecha o documento, mas o VueRite continua vivo."""

    def __init__(self, on_close: Callable[[], None]) -> None:
        super().__init__()
        self._on_close = on_close

    def closeEvent(self, event) -> None:
        # Só o X do usuário. Fechamento programático durante o refresh pós-separação
        # NÃO deve limpar o documento (isso fazia a arte sumir / "app fechar").
        event.ignore()
        if event.spontaneous():
            self._on_close()


class _ViewSubWindow(QMdiSubWindow):
    """Sub-janela extra (Window > New Window): Proof Positive ou uma separação."""

    closed = Signal(object)

    def __init__(self, kind: str, view: ImageCanvasView) -> None:
        super().__init__()
        self.kind = kind
        self.view = view
        self.setWidget(view)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def closeEvent(self, event) -> None:
        self.closed.emit(self)
        super().closeEvent(event)


class DocumentArea(QMdiArea):
    """Área MDI do SS4: a janela '<arquivo> : Proof Positive' (VueRite) e as janelas extras."""

    windows_changed = Signal()

    def __init__(self, canvas: VueRiteWidget, renderer: ViewRenderer, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ss4DocumentArea")
        self.setBackground(QColor("#3c3c3c"))
        self.canvas = canvas
        # O título vai na barra da sub-janela, como no SS4.
        canvas.header.hide()
        self._renderer = renderer
        self._close_document: Callable[[], None] = lambda: None
        self._extra: list[_ViewSubWindow] = []
        self._extra_tool = CanvasTool.MOVE
        self.link_views = False
        self._syncing = False
        self._compare_laid_out = False

        self.main_window = _DocumentSubWindow(lambda: self._close_document())
        self.main_window.setObjectName("ss4ProofPositiveWindow")
        self.main_window.setWidget(canvas)
        self.main_window.setWindowTitle(NO_DOCUMENT_TITLE)
        self.addSubWindow(self.main_window)
        self.main_window.hide()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh_windows)
        self._watch(canvas.active_view)
        self.subWindowActivated.connect(lambda _sub: self.windows_changed.emit())

    def set_close_document_handler(self, handler: Callable[[], None]) -> None:
        self._close_document = handler

    # ------------------------------------------------------------ documento
    def set_document_title(self, title: str | None) -> None:
        """Título da janela da imagem gerada; sem documento ela some."""
        self.canvas.set_title(title)
        text = title or NO_DOCUMENT_TITLE
        changed = self.main_window.windowTitle() != text
        self.main_window.setWindowTitle(text)
        if title and self.main_window.isHidden():
            self.main_window.show()
            self.canvas.fit_to_window()
            changed = True
        elif not title and not self.main_window.isHidden():
            self.main_window.hide()
            changed = True
        if changed:
            self.windows_changed.emit()
        if title and self._has_original_window():
            self.tile_compare_side_by_side()
        elif title and not self._extra:
            self._fill_main_window()

    def _has_original_window(self) -> bool:
        return any(w.kind == ORIGINAL_VIEW for w in self._extra)

    def _fill_main_window(self) -> None:
        """Sozinha na área, a janela principal ocupa todo o espaço disponível."""
        if self.main_window.isHidden() or self._extra:
            return
        self.main_window.setGeometry(self.viewport().rect())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._has_original_window() and not self.main_window.isHidden():
            self.tile_compare_side_by_side()
        else:
            self._fill_main_window()

    def ensure_compare_windows(self) -> None:
        """Garante Original (esquerda) + Imagem gerada (direita) lado a lado."""
        if self._renderer(ORIGINAL_VIEW) is None:
            return
        if self.main_window.isHidden():
            self.main_window.show()
        self.main_window.setWindowTitle(GENERATED_VIEW_TITLE)
        self.canvas.set_title(GENERATED_VIEW_TITLE)

        existing = next((w for w in self._extra if w.kind == ORIGINAL_VIEW), None)
        created = existing is None
        if existing is None:
            self.open_window(ORIGINAL_VIEW)
        else:
            rendered = self._renderer(ORIGINAL_VIEW)
            if rendered is not None:
                title, image = rendered
                existing.setWindowTitle(title)
                existing.view.update_image_from_pil(image)
        if created or not self._compare_laid_out:
            self.tile_compare_side_by_side()
            self._compare_laid_out = True
        self.windows_changed.emit()

    def tile_compare_side_by_side(self) -> None:
        """Original à esquerda, imagem gerada à direita."""
        if self.main_window.isHidden():
            return
        original = next((w for w in self._extra if w.kind == ORIGINAL_VIEW), None)
        area = self.viewport().rect()
        if original is None:
            self.main_window.setGeometry(area)
            return
        gap = 4
        half = max(120, (area.width() - gap) // 2)
        original.show()
        self.main_window.show()
        original.setGeometry(area.x(), area.y(), half, area.height())
        self.main_window.setGeometry(area.x() + half + gap, area.y(), area.width() - half - gap, area.height())
        original.view.fit_to_window()
        self.canvas.fit_to_window()

    # ------------------------------------------------------------ janelas
    def document_windows(self) -> list[QMdiSubWindow]:
        return [s for s in self.subWindowList() if not s.isHidden()]

    def extra_windows(self) -> list[_ViewSubWindow]:
        return list(self._extra)

    def current_window(self) -> QMdiSubWindow | None:
        current = self.currentSubWindow()
        if current is None or current.isHidden():
            return None if self.main_window.isHidden() else self.main_window
        return current

    def activate(self, window: QMdiSubWindow) -> None:
        self.setActiveSubWindow(window)
        self.windows_changed.emit()

    def open_window(self, kind: str) -> _ViewSubWindow | None:
        existing = next((w for w in self._extra if w.kind == kind), None)
        if existing is not None:
            rendered = self._renderer(kind)
            if rendered is None:
                return None
            title, image = rendered
            existing.setWindowTitle(title)
            existing.view.update_image_from_pil(image)
            self.activate(existing)
            return existing
        rendered = self._renderer(kind)
        if rendered is None:
            return None
        title, image = rendered
        view = ImageCanvasView()
        view.setBackgroundBrush(QColor("#3c3c3c"))
        view.set_tool(self._extra_tool)
        window = _ViewSubWindow(kind, view)
        window.setWindowTitle(title)
        window.closed.connect(self._on_extra_closed)
        self._extra.append(window)
        self.addSubWindow(window)
        area = self.viewport().rect()
        height = max(160, int(area.height() * 0.6))
        width = max(160, min(area.width(), int(height * image.width / max(1, image.height))))
        window.resize(width, height)
        view.set_image_from_pil(image, fit=False)
        window.show()
        view.fit_to_window()
        self._watch(view)
        self.activate(window)
        return window

    def _on_extra_closed(self, window: _ViewSubWindow) -> None:
        if window in self._extra:
            self._extra.remove(window)
        if self._has_original_window() and not self.main_window.isHidden():
            self.tile_compare_side_by_side()
        else:
            self._fill_main_window()
        self.windows_changed.emit()

    def close_extra_windows(self) -> None:
        for window in list(self._extra):
            window.close()
        self._compare_laid_out = False

    def close_current_extra(self) -> bool:
        """Close Window numa janela extra fecha só ela; na principal quem decide é o documento."""
        current = self.current_window()
        if isinstance(current, _ViewSubWindow):
            current.close()
            return True
        return False

    def schedule_refresh(self) -> None:
        if self._extra:
            self._refresh_timer.start(_REFRESH_DEBOUNCE_MS)

    def refresh_windows(self) -> None:
        """Reflete composite e separações atuais nas janelas extras (fecha as que sumiram)."""
        titles_changed = False
        for window in list(self._extra):
            rendered = self._renderer(window.kind)
            if rendered is None:
                window.close()
                continue
            title, image = rendered
            if window.windowTitle() != title:
                window.setWindowTitle(title)
                titles_changed = True
            window.view.update_image_from_pil(image)
        if titles_changed:
            self.windows_changed.emit()

    # ------------------------------------------------------------ vistas
    def views(self) -> list[ImageCanvasView]:
        return [self.canvas.active_view] + [w.view for w in self._extra]

    def active_view(self) -> ImageCanvasView:
        current = self.current_window()
        if isinstance(current, _ViewSubWindow):
            return current.view
        return self.canvas.active_view

    def set_navigation_tool(self, tool: CanvasTool | str) -> None:
        """Move/Zoom também valem nas janelas extras (que não editam)."""
        tool = CanvasTool(tool)
        self._extra_tool = tool if tool in _NAVIGATION_TOOLS else CanvasTool.MOVE
        for window in self._extra:
            window.view.set_tool(self._extra_tool)

    def match_zoom(self, source: ImageCanvasView) -> int:
        """Aplica o zoom e o centro de ``source`` em todas as vistas; devolve quantas vistas há."""
        views = self.views()
        self._copy_view(source, views)
        return len(views)

    def sync_from(self, source: ImageCanvasView) -> None:
        """Drag all windows: pan/zoom numa janela move as outras junto."""
        if self.link_views and not self._syncing:
            self._copy_view(source, self.views())

    def _copy_view(self, source: ImageCanvasView, views: list[ImageCanvasView]) -> None:
        self._syncing = True
        try:
            transform = source.transform()
            center = source.mapToScene(source.viewport().rect().center())
            for view in views:
                if view is not source:
                    view.setTransform(transform)
                    view.centerOn(center)
        finally:
            self._syncing = False

    def _watch(self, view: ImageCanvasView) -> None:
        view.horizontalScrollBar().valueChanged.connect(lambda _v, v=view: self.sync_from(v))
        view.verticalScrollBar().valueChanged.connect(lambda _v, v=view: self.sync_from(v))
        view.viewport().installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel and self.link_views:
            view = obj.parent()
            if isinstance(view, ImageCanvasView):
                QTimer.singleShot(0, lambda v=view: self._sync_if_open(v))
        return super().eventFilter(obj, event)

    def _sync_if_open(self, view: ImageCanvasView) -> None:
        if any(v is view for v in self.views()):
            self.sync_from(view)
