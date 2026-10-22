"""Operações usadas na versão Clean (ajuste por saturação na barra de canais)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from packages.core.models.channel_info import ChannelInfo
from packages.core.services.channel_ops import clone_channel


@dataclass
class SeparationEdit:
    channels: list[ChannelInfo]
    changed: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    added: set[str] = field(default_factory=set)
    message: str = ""

    @property
    def is_noop(self) -> bool:
        return not (self.changed or self.removed or self.added)


def coverage(channel: ChannelInfo) -> float:
    return 0.0 if channel.mask is None else float(np.asarray(channel.mask, dtype=np.float32).mean())


def source_mask(channel: ChannelInfo) -> np.ndarray:
    base = channel.raw_mask if channel.raw_mask is not None else channel.mask
    return np.clip(np.asarray(base, dtype=np.float32), 0.0, 1.0)


def _with_raw(channel: ChannelInfo, raw: np.ndarray) -> ChannelInfo:
    out = clone_channel(channel)
    out.set_mask(np.clip(raw, 0.0, 1.0).astype(np.float32))
    return out


def saturation_range(mask: np.ndarray, high: int, low: int) -> np.ndarray:
    m = np.clip(np.asarray(mask, dtype=np.float32), 0.0, 1.0)
    high = int(np.clip(high, 0, 100))
    low = int(np.clip(low, 0, 100))
    white_point = max(0.01, 1.0 - high / 100.0)
    floor = (100 - low) / 100.0
    out = np.clip(m / white_point, 0.0, 1.0) if high else m.copy()
    if floor > 0:
        out = np.where(m < floor, 0.0, out)
    return out.astype(np.float32)


def adjust_saturation_range(
    channels: list[ChannelInfo], target_ids: list[str] | set[str], high: int, low: int
) -> SeparationEdit:
    targets = set(target_ids)
    changed: set[str] = set()
    out: list[ChannelInfo] = []
    for ch in channels:
        if ch.id in targets and ch.mask is not None and (high or low < 100):
            out.append(_with_raw(ch, saturation_range(source_mask(ch), high, low)))
            changed.add(ch.id)
        else:
            out.append(ch)
    return SeparationEdit(
        out,
        changed=changed,
        message=(
            f"Faixa de saturação aplicada em {len(changed)} separação(ões) "
            f"(encharcar {high}, aliviar {low})."
        ),
    )
