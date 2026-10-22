from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

import numpy as np
from scipy import ndimage

from packages.core.models.channel_info import ChannelInfo
from packages.core.services.channel_ops import clone_channel
from packages.prepress.models import WhiteConfig
from packages.prepress.operations import PrepressPlate, make_white_plates, mm_to_pixels


def channels_to_plates(channels: list[ChannelInfo]) -> tuple[PrepressPlate, ...]:
    plates: list[PrepressPlate] = []
    for ch in channels:
        if ch.mask is None:
            continue
        plates.append(
            PrepressPlate(
                key=ch.key or ch.id,
                label=ch.name,
                color_rgb=tuple(ch.color_rgb),
                mask=ch.mask,
                role=ch.role,
                export_name=ch.export_name or ch.name.upper(),
            )
        )
    return tuple(plates)


def plates_to_channels(plates: tuple[PrepressPlate, ...]) -> list[ChannelInfo]:
    out: list[ChannelInfo] = []
    for plate in plates:
        out.append(
            ChannelInfo.create(
                name=plate.label,
                color_rgb=plate.color_rgb,
                mask=plate.mask.copy(),
                channel_id=f"scf8:{plate.key}",
                key=plate.key,
                export_name=plate.export_name,
                role=plate.role,
            )
        )
    return out


def append_underbase(
    channels: list[ChannelInfo],
    *,
    dpi: float,
    alpha,
    config: WhiteConfig | None = None,
) -> list[ChannelInfo]:
    """Create Underbase SS4 — união de máscaras + choke (FAV8 prepress)."""
    cfg = config or WhiteConfig(mode="underbase")
    plates = channels_to_plates(channels)
    if not plates:
        return list(channels)
    white = make_white_plates(plates, cfg, dpi, alpha=alpha)
    if not white:
        return list(channels)
    existing_keys = {ch.key for ch in channels}
    merged = list(channels)
    for ch in plates_to_channels(white):
        if ch.key in existing_keys:
            continue
        merged.insert(0, ch)
    return merged


def is_underbase_channel(ch: ChannelInfo) -> bool:
    return ch.role == "underbase" or "underbase" in f"{ch.name} {ch.key or ''}".lower()


def find_underbase(channels: list[ChannelInfo]) -> ChannelInfo | None:
    return next((ch for ch in channels if is_underbase_channel(ch)), None)


def choke_base(base: np.ndarray, config: WhiteConfig, dpi: float, alpha=None) -> np.ndarray:
    """Underbase a partir de uma base fixa: corta densidade mínima e recua a borda (choke)."""
    mask = np.clip(np.asarray(base, dtype=np.float32), 0.0, 1.0).copy()
    mask[mask < config.min_density] = 0.0
    radius = mm_to_pixels(config.choke_mm, dpi)
    if radius > 0:
        y, x = np.ogrid[-radius : radius + 1, -radius : radius + 1]
        mask = ndimage.grey_erosion(mask, footprint=(x * x + y * y) <= radius * radius).astype(np.float32)
    if alpha is not None:
        mask = np.minimum(mask, np.asarray(alpha, dtype=np.float32))
    return mask.astype(np.float32)


UnderbaseStyle = Literal["actual", "solid"]
UnderbaseMode = Literal["static", "live"]


@dataclass(frozen=True)
class LiveUnderbaseSettings:
    """Opções da janela 'Live Underbase Properties' (SS4)."""

    excluded: frozenset[str] = field(default_factory=frozenset)
    combine: bool = False
    apply_to_all: bool = True
    choke_pt: float = 0.5
    style: UnderbaseStyle = "actual"
    min_density: float = 0.02


def pt_to_mm(points: float) -> float:
    return float(points) * 25.4 / 72.0


def _union_mask(sources: list[ChannelInfo], settings: LiveUnderbaseSettings, dpi: float) -> np.ndarray | None:
    """União das separações marcadas na janela (a Top White marcada também leva base)."""
    plates = tuple(
        replace(p, role="process", key=f"live:{p.key}") if p.role == "highlight" or p.key.endswith("_white") else p
        for p in channels_to_plates(sources)
    )
    if not plates:
        return None
    union = make_white_plates(
        plates, WhiteConfig(mode="underbase", choke_mm=0.0, min_density=settings.min_density), dpi
    )
    return np.asarray(union[0].mask, dtype=np.float32) if union else None


def live_underbase_mask(
    channels: list[ChannelInfo],
    settings: LiveUnderbaseSettings,
    *,
    dpi: float,
    alpha=None,
    cap: np.ndarray | None = None,
) -> np.ndarray | None:
    """Underbase das separações incluídas: união (motor) → teto do motor → Solid → choke em pt.

    ``cap`` é a Underbase que o motor gerou na separação: a Live nunca passa dela e, com
    separações desmarcadas, fica na proporção da tinta das separações escolhidas.
    """
    colors = [ch for ch in channels if ch.mask is not None and not is_underbase_channel(ch)]
    chosen = _union_mask([ch for ch in colors if ch.id not in settings.excluded], settings, dpi)
    if chosen is None:
        return None
    mask = chosen
    if cap is not None and np.shape(cap) == mask.shape:
        limit = np.asarray(cap, dtype=np.float32)
        if settings.excluded:
            full = _union_mask(colors, settings, dpi)
            share = np.divide(chosen, full, out=np.zeros_like(chosen), where=full > 1e-6)
            limit = limit * np.clip(share, 0.0, 1.0)
        mask = np.minimum(mask, limit)
    if settings.style == "solid":
        mask = (mask > settings.min_density).astype(np.float32)
    config = WhiteConfig(mode="underbase", choke_mm=pt_to_mm(settings.choke_pt), min_density=settings.min_density)
    return choke_base(mask, config, dpi, alpha)


def rebuild_underbase(
    channels: list[ChannelInfo],
    *,
    dpi: float,
    alpha,
    config: WhiteConfig,
    base: np.ndarray | None = None,
) -> tuple[list[ChannelInfo], ChannelInfo | None]:
    """Create Underbase com edição: refaz a Underbase existente (nunca deixa duas).

    ``base`` é a máscara-fonte de uma Underbase vinda do motor; sem ela a Underbase é a
    união das separações de cor (Live Underbase). Retorna (lista nova, underbase nova).
    """
    existing = find_underbase(channels)
    if existing is None:
        merged = append_underbase(channels, dpi=dpi, alpha=alpha, config=config)
        return merged, find_underbase(merged) if len(merged) != len(channels) else None
    if base is not None:
        mask = choke_base(base, config, dpi, alpha)
    else:
        others = [ch for ch in channels if ch.id != existing.id]
        plates = channels_to_plates(others)
        if not plates:
            return list(channels), None
        white = make_white_plates(plates, WhiteConfig(
            mode="underbase", choke_mm=config.choke_mm, min_density=config.min_density
        ), dpi, alpha=alpha)
        if not white:
            return list(channels), None
        mask = np.asarray(white[0].mask, dtype=np.float32)
    rebuilt = clone_channel(existing)
    rebuilt.set_mask(mask)
    out = [rebuilt if ch.id == existing.id else ch for ch in channels]
    if config.mode == "both" and not any(
        ch.role == "highlight" for ch in out
    ):
        top = make_white_plates(channels_to_plates([c for c in out if c.id != existing.id]),
                                WhiteConfig(mode="top_white", choke_mm=config.choke_mm,
                                            min_density=config.min_density), dpi, alpha=alpha)
        out.extend(plates_to_channels(top))
    return out, rebuilt
