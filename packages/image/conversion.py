from __future__ import annotations

import numpy as np
from PIL import Image
from PySide6.QtGui import QImage, QPixmap


def pil_to_numpy(image: Image.Image) -> np.ndarray:
    """Convert PIL RGB/RGBA image to NumPy array (RGB order)."""
    rgb = image.convert("RGB")
    return np.array(rgb, dtype=np.uint8)


def numpy_to_pil(array: np.ndarray, mode: str = "RGB") -> Image.Image:
    """Convert NumPy array to PIL Image."""
    if array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    return Image.fromarray(array, mode=mode)


def bgr_to_rgb(array: np.ndarray) -> np.ndarray:
    """Convert OpenCV BGR array to RGB."""
    if array.ndim == 3 and array.shape[2] == 3:
        return array[:, :, ::-1].copy()
    return array


def rgb_to_bgr(array: np.ndarray) -> np.ndarray:
    """Convert RGB array to OpenCV BGR."""
    if array.ndim == 3 and array.shape[2] == 3:
        return array[:, :, ::-1].copy()
    return array


def pil_to_qpixmap(image: Image.Image) -> QPixmap:
    """Convert PIL Image to QPixmap for Qt display.

    Copia os bytes para o Qt: ImageQt compartilha o buffer do PIL e, quando o
    garbage collector libera a imagem, o app crasha ao pintar o resultado da
    separação (access violation em qwindows/Qt6Gui).
    """
    if image.mode == "RGBA":
        data = np.ascontiguousarray(np.array(image, dtype=np.uint8))
        qimage = QImage(
            data.data, data.shape[1], data.shape[0], data.strides[0], QImage.Format.Format_RGBA8888
        ).copy()
    else:
        rgb = image.convert("RGB")
        data = np.ascontiguousarray(np.array(rgb, dtype=np.uint8))
        qimage = QImage(
            data.data, data.shape[1], data.shape[0], data.strides[0], QImage.Format.Format_RGB888
        ).copy()
    return QPixmap.fromImage(qimage)
