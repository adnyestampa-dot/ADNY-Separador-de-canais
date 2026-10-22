from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image


@dataclass
class ImageDocument:
    """In-memory image document with normalized RGB data."""

    path: str | None
    width: int
    height: int
    dpi: tuple[float, float] = (72.0, 72.0)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    _pil_image: Image.Image | None = field(default=None, repr=False)
    _array: np.ndarray | None = field(default=None, repr=False)
    _alpha: np.ndarray | None = field(default=None, repr=False)

    @classmethod
    def from_pil(cls, image: Image.Image, path: str | None = None) -> ImageDocument:
        rgba = image.convert("RGBA")
        rgb = rgba.convert("RGB")
        alpha = np.asarray(rgba.getchannel("A"), dtype=np.float32) / 255.0
        dpi = image.info.get("dpi", (72.0, 72.0))
        if isinstance(dpi, tuple) and len(dpi) >= 2:
            dpi_tuple = (float(dpi[0]), float(dpi[1]))
        else:
            dpi_tuple = (72.0, 72.0)
        return cls(
            path=path,
            width=rgb.width,
            height=rgb.height,
            dpi=dpi_tuple,
            _pil_image=rgb,
            _alpha=alpha,
        )

    @property
    def pil_image(self) -> Image.Image:
        if self._pil_image is None:
            raise ValueError("Documento sem imagem carregada")
        return self._pil_image

    @property
    def array(self) -> np.ndarray:
        if self._array is None:
            self._array = np.array(self.pil_image, dtype=np.uint8)
        return self._array

    @property
    def alpha(self) -> np.ndarray:
        """Alpha original normalizado, preservado mesmo com a visualização RGB."""
        if self._alpha is None:
            self._alpha = np.ones((self.height, self.width), dtype=np.float32)
        return self._alpha.copy()

    def set_result_image(self, image: Image.Image) -> None:
        rgba = image.convert("RGBA")
        self._alpha = np.asarray(rgba.getchannel("A"), dtype=np.float32) / 255.0
        self._pil_image = rgba.convert("RGB")
        self._array = np.array(self._pil_image, dtype=np.uint8)
        self.width = self._pil_image.width
        self.height = self._pil_image.height

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "width": self.width,
            "height": self.height,
            "dpi": self.dpi,
        }
