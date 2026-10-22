from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image

from packages.image.channel_adjust import ChannelAdjustments, apply_channel_adjustments


def _build_layer_rgba(
    shape: tuple[int, int],
    mask: np.ndarray,
    color: tuple[int, int, int],
) -> Image.Image:
    h, w = shape
    layer = np.zeros((h, w, 4), dtype=np.uint8)
    layer[:, :, 0] = color[0]
    layer[:, :, 1] = color[1]
    layer[:, :, 2] = color[2]
    m = mask.astype(np.float32)
    if m.max() > 1.0:
        m = m / 255.0
    layer[:, :, 3] = (np.clip(m, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(layer)


@dataclass
class ChannelInfo:
    id: str
    name: str
    color_rgb: tuple[int, int, int]
    key: str | None = None
    export_name: str | None = None
    role: str = "process"
    engine_version: str | None = None
    manifest_version: int | None = None
    profile_hash: str | None = None
    visible: bool = True
    opacity: float = 1.0
    adjustments: ChannelAdjustments = field(default_factory=ChannelAdjustments)
    _raw_mask: np.ndarray | None = field(default=None, repr=False)
    _mask: np.ndarray | None = field(default=None, repr=False)
    _layer_image: Image.Image | None = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        name: str,
        color_rgb: tuple[int, int, int],
        mask: np.ndarray | None = None,
        *,
        channel_id: str | None = None,
        key: str | None = None,
        export_name: str | None = None,
        role: str = "process",
        engine_version: str | None = None,
        manifest_version: int | None = None,
        profile_hash: str | None = None,
    ) -> ChannelInfo:
        ch = cls(
            id=channel_id or str(uuid.uuid4()),
            name=name,
            color_rgb=color_rgb,
            key=key,
            export_name=export_name,
            role=role,
            engine_version=engine_version,
            manifest_version=manifest_version,
            profile_hash=profile_hash,
        )
        if mask is not None:
            ch.set_mask(mask)
        return ch

    @property
    def mask(self) -> np.ndarray | None:
        return self._mask

    @property
    def raw_mask(self) -> np.ndarray | None:
        return self._raw_mask

    @property
    def layer_image(self) -> Image.Image | None:
        return self._layer_image

    def set_layer_image(self, image: Image.Image) -> None:
        self._layer_image = image

    def set_mask(self, mask: np.ndarray) -> None:
        self._raw_mask = np.clip(mask.astype(np.float32), 0, 1).copy()
        self._apply_adjustments()

    def set_adjustments(self, adjustments: ChannelAdjustments) -> None:
        self.adjustments = adjustments.copy()
        self._apply_adjustments()

    def _apply_adjustments(self) -> None:
        if self._raw_mask is None:
            return
        self._mask = apply_channel_adjustments(self._raw_mask, self.adjustments)
        self._rebuild_layer()

    def set_color_rgb(self, rgb: tuple[int, int, int]) -> None:
        self.color_rgb = rgb
        self._rebuild_layer()

    def merge_from(self, other: ChannelInfo) -> None:
        if self._raw_mask is None or other._raw_mask is None:
            return
        self._raw_mask = np.clip(self._raw_mask + other._raw_mask, 0, 1).astype(np.float32)
        if other.name not in self.name:
            self.name = f"{self.name} + {other.name}"
        self._apply_adjustments()

    def _rebuild_layer(self) -> None:
        if self._mask is None:
            return
        h, w = self._mask.shape[:2]
        self._layer_image = _build_layer_rgba((h, w), self._mask, self.color_rgb)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "color_rgb": self.color_rgb,
            "key": self.key,
            "export_name": self.export_name,
            "role": self.role,
            "engine_version": self.engine_version,
            "manifest_version": self.manifest_version,
            "profile_hash": self.profile_hash,
            "visible": self.visible,
            "opacity": self.opacity,
            "adjustments": {
                "high_saturation": self.adjustments.high_saturation,
                "low_saturation": self.adjustments.low_saturation,
                "tint": self.adjustments.tint,
                "choke": self.adjustments.choke,
            },
        }
