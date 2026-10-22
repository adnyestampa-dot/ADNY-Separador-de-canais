from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from packages.image.morph_processor import apply_choke


@dataclass
class ChannelAdjustments:
    high_saturation: float = 1.0
    low_saturation: float = 1.0
    tint: float = 1.0
    choke: int = 0

    def copy(self) -> ChannelAdjustments:
        return ChannelAdjustments(
            high_saturation=self.high_saturation,
            low_saturation=self.low_saturation,
            tint=self.tint,
            choke=self.choke,
        )


def apply_channel_adjustments(
    raw: np.ndarray,
    adj: ChannelAdjustments,
    *,
    fast_preview: bool = False,
) -> np.ndarray:
    """Aplica ajustes mecânicos/cromáticos sobre a máscara bruta do canal."""
    import cv2

    source = raw
    restore_shape = None
    if fast_preview and raw.size > 250_000:
        h, w = raw.shape[:2]
        scale = min(1.0, (250_000 / max(raw.size, 1)) ** 0.5)
        nh, nw = max(1, int(h * scale)), max(1, int(w * scale))
        source = cv2.resize(raw.astype(np.float32), (nw, nh), interpolation=cv2.INTER_AREA)
        restore_shape = (h, w)

    m = _apply_adjustments_core(source, adj)

    if restore_shape is not None:
        m = cv2.resize(m, (restore_shape[1], restore_shape[0]), interpolation=cv2.INTER_LINEAR)

    return m


def _apply_adjustments_core(raw: np.ndarray, adj: ChannelAdjustments) -> np.ndarray:
    """Núcleo dos ajustes (máscara já na escala de trabalho)."""
    m = np.clip(raw.astype(np.float32), 0.0, 1.0)

    if adj.tint != 1.0:
        m = np.clip(m * float(adj.tint), 0.0, 1.0)

    if adj.high_saturation != 1.0:
        t = np.clip((m - 0.35) / 0.65, 0.0, 1.0)
        boost = 1.0 + (float(adj.high_saturation) - 1.0) * t
        m = np.clip(m * boost, 0.0, 1.0)

    if adj.low_saturation != 1.0:
        floor = 0.04 * float(adj.low_saturation)
        m = np.where(m < floor, 0.0, m)

    if adj.choke > 0:
        m = apply_choke(m, int(adj.choke))

    return np.clip(m, 0.0, 1.0).astype(np.float32)
