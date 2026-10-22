from __future__ import annotations

from typing import Sequence

import numpy as np
from PIL import Image

from packages.core.models.channel_info import ChannelInfo


def _mask01(channel: ChannelInfo) -> np.ndarray | None:
    mask = channel.mask
    if mask is None:
        return None
    values = mask.astype(np.float32, copy=False)
    if values.max() > 1.0:
        values = values / 255.0
    return values * float(channel.opacity)


def channel_density_at(
    channels: Sequence[ChannelInfo],
    x: int,
    y: int,
    *,
    visibility: dict[str, bool] | None = None,
) -> dict[str, float]:
    """Densidade (0–1) por canal visível na coordenada de imagem."""
    out: dict[str, float] = {}
    for channel in channels:
        if visibility is not None and not visibility.get(channel.id, channel.visible):
            continue
        if not channel.visible and visibility is None:
            continue
        mask = _mask01(channel)
        if mask is None:
            continue
        h, w = mask.shape[:2]
        if not (0 <= x < w and 0 <= y < h):
            continue
        out[channel.name] = float(np.clip(mask[y, x], 0.0, 1.0))
    return out


def format_density_status(densities: dict[str, float], x: int, y: int) -> str:
    if not densities:
        return f"Densidade @ ({x}, {y}): —"
    parts = [f"{name}={value:.0%}" for name, value in list(densities.items())[:4]]
    extra = len(densities) - len(parts)
    suffix = f" +{extra}" if extra > 0 else ""
    return f"@ ({x},{y}) " + " · ".join(parts) + suffix


def mask_thumbnail(
    mask: np.ndarray,
    *,
    size: int = 48,
    ink_rgb: tuple[int, int, int] | None = None,
) -> Image.Image:
    """Miniatura de chapa para a barra de separações."""
    values = mask.astype(np.float32, copy=False)
    if values.max() > 1.0:
        values = values / 255.0
    h, w = values.shape[:2]
    img = Image.fromarray((np.clip(values, 0, 1) * 255).astype(np.uint8), mode="L")
    img = img.resize((size, size), Image.Resampling.BILINEAR)
    if ink_rgb is None:
        return img.convert("RGB")
    rgb = Image.new("RGB", (size, size), ink_rgb)
    rgb.paste(img, mask=img)
    return rgb


def compose_film_preview(
    channels: Sequence[ChannelInfo],
    shape: tuple[int, int],
    *,
    visibility: dict[str, bool] | None = None,
) -> Image.Image:
    """Composite estilo filme: fundo preto, tinta branca (máximo das chapas visíveis)."""
    h, w = shape
    acc = np.zeros((h, w), dtype=np.float32)
    for channel in channels:
        if visibility is not None and not visibility.get(channel.id, channel.visible):
            continue
        if not channel.visible and visibility is None:
            continue
        mask = _mask01(channel)
        if mask is None:
            continue
        if mask.shape[:2] != (h, w):
            continue
        acc = np.maximum(acc, mask)
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    v = (np.clip(acc, 0, 1) * 255).astype(np.uint8)
    rgb[:, :, 0] = v
    rgb[:, :, 1] = v
    rgb[:, :, 2] = v
    return Image.fromarray(rgb, mode="RGB")
