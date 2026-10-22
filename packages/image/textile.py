from __future__ import annotations

from typing import Sequence

import numpy as np
from PIL import Image

from packages.core.models.channel_info import ChannelInfo
from packages.core.models.project_state import TextilePreset


GROUND_COLORS: dict[TextilePreset, tuple[int, int, int]] = {
    TextilePreset.PRETO: (20, 20, 20),
    TextilePreset.BRANCO: (240, 240, 240),
    TextilePreset.CINZA_NEUTRO: (128, 128, 128),
    TextilePreset.MARINHO: (0, 32, 96),
}


def ground_color_for_preset(preset: TextilePreset) -> tuple[int, int, int]:
    return GROUND_COLORS.get(preset, (20, 20, 20))


def ground_color_for_state(state) -> tuple[int, int, int]:
    """Cor de ground efetiva do projeto: cor personalizada ou a do preset de tecido."""
    override = getattr(state, "ground_rgb_override", None)
    if override is not None:
        return tuple(int(max(0, min(255, c))) for c in override)  # type: ignore[return-value]
    return ground_color_for_preset(state.textile_preset)


NEUTRAL_GROUND_RGB: tuple[int, int, int] = (255, 255, 255)


def display_ground_for_state(state) -> tuple[int, int, int]:
    """Fundo do preview na tela: cor do tecido, ou neutro com 'Show Textile Color' desligado."""
    if not getattr(state, "show_textile_color", True):
        return NEUTRAL_GROUND_RGB
    return ground_color_for_state(state)


PREVIEW_MAX_PIXELS = 480_000


def preview_dimensions(
    h: int, w: int, max_pixels: int = PREVIEW_MAX_PIXELS
) -> tuple[int, int]:
    if h * w <= max_pixels:
        return h, w
    scale = (max_pixels / (h * w)) ** 0.5
    return max(1, int(h * scale)), max(1, int(w * scale))


def _resize_mask(mask: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    import cv2

    h, w = shape
    m = mask.astype(np.float32, copy=False)
    if m.shape[0] == h and m.shape[1] == w:
        return m
    if m.max() > 1:
        m = m / 255.0
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA)


def _channel_shown(ch: ChannelInfo, visibility: dict[str, bool] | None) -> bool:
    if visibility is not None:
        return visibility.get(ch.id, ch.visible)
    return ch.visible


def _overprint_base(shape: tuple[int, int], *, dark_fabric: bool) -> np.ndarray:
    h, w = shape
    if dark_fabric:
        return np.zeros((h, w, 3), dtype=np.float32)
    return np.ones((h, w, 3), dtype=np.float32)


def _apply_overprint_layer(
    base: np.ndarray,
    mask: np.ndarray,
    color_rgb: tuple[int, int, int],
    opacity: float,
) -> np.ndarray:
    m = mask.astype(np.float32, copy=False)
    if m.max() > 1:
        m = m / 255.0
    weight = np.clip(m * opacity, 0.0, 1.0)
    ink = np.array(color_rgb, dtype=np.float32) / 255.0
    return base * (1.0 - weight[..., np.newaxis]) + ink * weight[..., np.newaxis]


def compose_channels_overprint(
    channels: Sequence[ChannelInfo],
    shape: tuple[int, int],
    *,
    visibility: dict[str, bool] | None = None,
    dark_fabric: bool = True,
) -> Image.Image:
    """Compõe canais no modelo overprint (mesma lógica do preview FAV5)."""
    h, w = shape
    base = _overprint_base((h, w), dark_fabric=dark_fabric)

    for ch in channels:
        if not _channel_shown(ch, visibility) or ch.mask is None:
            continue
        base = _apply_overprint_layer(base, ch.mask, ch.color_rgb, ch.opacity)

    return Image.fromarray((np.clip(base, 0, 1) * 255).astype(np.uint8), mode="RGB")


def compose_channels_overprint_fast(
    channels: Sequence[ChannelInfo],
    shape: tuple[int, int],
    *,
    max_pixels: int = PREVIEW_MAX_PIXELS,
    visibility: dict[str, bool] | None = None,
    dark_fabric: bool = True,
) -> Image.Image:
    """Preview interativo com overprint em resolução reduzida."""
    h, w = shape
    ph, pw = preview_dimensions(h, w, max_pixels)
    if (ph, pw) == (h, w):
        return compose_channels_overprint(
            channels, shape, visibility=visibility, dark_fabric=dark_fabric
        )

    base = _overprint_base((ph, pw), dark_fabric=dark_fabric)
    for ch in channels:
        if not _channel_shown(ch, visibility) or ch.mask is None:
            continue
        mask = _resize_mask(ch.mask, (ph, pw))
        base = _apply_overprint_layer(base, mask, ch.color_rgb, ch.opacity)

    out = Image.fromarray((np.clip(base, 0, 1) * 255).astype(np.uint8), mode="RGB")
    return _upscale_preview_image(out, (h, w))


def compose_overprint_with_live_mask(
    channels: Sequence[ChannelInfo],
    shape: tuple[int, int],
    editing_channel_id: str,
    live_mask: np.ndarray,
    *,
    live_opacity: float | None = None,
    live_color_rgb: tuple[int, int, int] | None = None,
    max_pixels: int = PREVIEW_MAX_PIXELS,
    visibility: dict[str, bool] | None = None,
    dark_fabric: bool = True,
) -> Image.Image:
    """Overprint ao vivo — substitui só a máscara do canal em edição."""
    h, w = shape
    ph, pw = preview_dimensions(h, w, max_pixels)
    base = _overprint_base((ph, pw), dark_fabric=dark_fabric)
    live_mask_f = np.clip(_resize_mask(live_mask, (ph, pw)), 0.0, 1.0)

    for ch in channels:
        if not _channel_shown(ch, visibility):
            continue
        if ch.id == editing_channel_id:
            mask = live_mask_f
            opacity = live_opacity if live_opacity is not None else ch.opacity
            color_rgb = live_color_rgb if live_color_rgb is not None else ch.color_rgb
        else:
            if ch.mask is None:
                continue
            mask = _resize_mask(ch.mask, (ph, pw))
            opacity = ch.opacity
            color_rgb = ch.color_rgb
        base = _apply_overprint_layer(base, mask, color_rgb, opacity)

    out = Image.fromarray((np.clip(base, 0, 1) * 255).astype(np.uint8), mode="RGB")
    return _upscale_preview_image(out, (h, w))


def compose_with_ground(
    channels: Sequence[ChannelInfo],
    shape: tuple[int, int],
    ground_rgb: tuple[int, int, int],
    *,
    visibility: dict[str, bool] | None = None,
) -> Image.Image:
    """Composite channels over textile ground color."""
    h, w = shape
    base = np.empty((h, w, 3), dtype=np.float32)
    base[:, :, 0] = ground_rgb[0]
    base[:, :, 1] = ground_rgb[1]
    base[:, :, 2] = ground_rgb[2]

    for ch in channels:
        if not _channel_shown(ch, visibility) or ch.mask is None:
            continue
        mask = ch.mask.astype(np.float32, copy=False)
        if mask.max() > 1:
            mask = mask / 255.0
        alpha = mask * ch.opacity
        color = np.array(ch.color_rgb, dtype=np.float32)
        inv = 1.0 - alpha
        base[:, :, 0] = base[:, :, 0] * inv + color[0] * alpha
        base[:, :, 1] = base[:, :, 1] * inv + color[1] * alpha
        base[:, :, 2] = base[:, :, 2] * inv + color[2] * alpha

    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), mode="RGB")


def _upscale_preview_image(img: Image.Image, target_shape: tuple[int, int]) -> Image.Image:
    """Garante preview interativo na mesma resolução do documento (evita saltos de zoom)."""
    th, tw = target_shape
    if img.size == (tw, th):
        return img
    return img.resize((tw, th), Image.Resampling.BILINEAR)


def compose_with_ground_fast(
    channels: Sequence[ChannelInfo],
    shape: tuple[int, int],
    ground_rgb: tuple[int, int, int],
    *,
    max_pixels: int = PREVIEW_MAX_PIXELS,
    visibility: dict[str, bool] | None = None,
) -> Image.Image:
    """Preview interativo — compõe em resolução reduzida para manter a UI fluida."""
    h, w = shape
    ph, pw = preview_dimensions(h, w, max_pixels)
    if (ph, pw) == (h, w):
        return compose_with_ground(channels, shape, ground_rgb, visibility=visibility)

    base = np.empty((ph, pw, 3), dtype=np.float32)
    base[:, :, 0] = ground_rgb[0]
    base[:, :, 1] = ground_rgb[1]
    base[:, :, 2] = ground_rgb[2]

    for ch in channels:
        if not _channel_shown(ch, visibility) or ch.mask is None:
            continue
        mask = _resize_mask(ch.mask, (ph, pw))
        alpha = mask * ch.opacity
        color = np.array(ch.color_rgb, dtype=np.float32)
        inv = 1.0 - alpha
        base[:, :, 0] = base[:, :, 0] * inv + color[0] * alpha
        base[:, :, 1] = base[:, :, 1] * inv + color[1] * alpha
        base[:, :, 2] = base[:, :, 2] * inv + color[2] * alpha

    out = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), mode="RGB")
    return _upscale_preview_image(out, (h, w))


def compose_with_live_mask(
    channels: Sequence[ChannelInfo],
    shape: tuple[int, int],
    ground_rgb: tuple[int, int, int],
    editing_channel_id: str,
    live_mask: np.ndarray,
    *,
    live_opacity: float | None = None,
    live_color_rgb: tuple[int, int, int] | None = None,
    max_pixels: int = PREVIEW_MAX_PIXELS,
    visibility: dict[str, bool] | None = None,
) -> Image.Image:
    """Compõe preview substituindo só a máscara do canal em edição (mais rápido)."""
    h, w = shape
    ph, pw = preview_dimensions(h, w, max_pixels)

    base = np.empty((ph, pw, 3), dtype=np.float32)
    base[:, :, 0] = ground_rgb[0]
    base[:, :, 1] = ground_rgb[1]
    base[:, :, 2] = ground_rgb[2]

    live_mask_f = _resize_mask(live_mask, (ph, pw))
    live_mask_f = np.clip(live_mask_f, 0.0, 1.0)

    for ch in channels:
        if not _channel_shown(ch, visibility):
            continue
        if ch.id == editing_channel_id:
            mask = live_mask_f
            opacity = live_opacity if live_opacity is not None else ch.opacity
        else:
            if ch.mask is None:
                continue
            mask = _resize_mask(ch.mask, (ph, pw))
            opacity = ch.opacity

        alpha = mask * opacity
        if ch.id == editing_channel_id and live_color_rgb is not None:
            color = np.array(live_color_rgb, dtype=np.float32)
        else:
            color = np.array(ch.color_rgb, dtype=np.float32)
        inv = 1.0 - alpha
        base[:, :, 0] = base[:, :, 0] * inv + color[0] * alpha
        base[:, :, 1] = base[:, :, 1] * inv + color[1] * alpha
        base[:, :, 2] = base[:, :, 2] * inv + color[2] * alpha

    out = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), mode="RGB")
    return _upscale_preview_image(out, (h, w))
