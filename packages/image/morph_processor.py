from __future__ import annotations

import cv2
import numpy as np


def _elliptical_kernel(radius_px: int) -> np.ndarray:
    size = 2 * int(radius_px) + 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


def apply_choke(channel: np.ndarray, radius_px: int = 2) -> np.ndarray:
    """Recuo (choke) do canal via erosão morfológica elíptica."""
    if radius_px <= 0:
        return channel.astype(np.float32)
    kernel = _elliptical_kernel(radius_px)
    eroded = cv2.erode(channel.astype(np.float32), kernel, iterations=1)
    return np.clip(eroded, 0.0, 1.0).astype(np.float32)
