from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QRect
from PySide6.QtGui import QPainter, QPaintDevice

from packages.image.conversion import pil_to_qpixmap


def proof_target_rect(page_w: int, page_h: int, image_w: int, image_h: int) -> QRect:
    """Maior retângulo com a proporção da arte, centralizado na área imprimível da página."""
    scale = min(page_w / max(1, image_w), page_h / max(1, image_h))
    w, h = max(1, int(image_w * scale)), max(1, int(image_h * scale))
    return QRect((page_w - w) // 2, (page_h - h) // 2, w, h)


def paint_color_proof(device: QPaintDevice, image: Image.Image) -> bool:
    """Desenha o composite (Proof Positive) no dispositivo — QPrinter na impressão real."""
    rgb = image.convert("RGB")
    painter = QPainter()
    if not painter.begin(device):
        return False
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        target = proof_target_rect(device.width(), device.height(), rgb.width, rgb.height)
        painter.drawPixmap(target, pil_to_qpixmap(rgb))
    finally:
        painter.end()
    return True
