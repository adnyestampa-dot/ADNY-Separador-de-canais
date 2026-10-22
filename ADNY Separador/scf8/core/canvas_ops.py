"""Edição no VueRite (Saturate, Desaturate, Eraser, Edit > Delete), fora do motor.

As funções trabalham sobre as máscaras brutas das separações (0..1). O traço de pincel
(``BrushStroke``) acumula as pinceladas em cópias de trabalho; o presenter grava o traço
inteiro como UM passo de undo ao soltar o mouse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from packages.core.models.channel_info import ChannelInfo
from scf8.core.separation_ops import SeparationEdit, _with_raw, source_mask

BrushTool = Literal["saturate", "desaturate", "eraser"]
SaturationRange = Literal["low", "mid", "high"]

INK_EPS = 1.0 / 255.0
DEFAULT_BRUSH_DIAMETER = 32
DEFAULT_HARDNESS = 0.5
DEFAULT_FLOW = 0.35
DEFAULT_RANGE: SaturationRange = "low"
SATURATION_RANGES: tuple[SaturationRange, ...] = ("low", "mid", "high")


# ------------------------------------------------------------------ pincel

def brush_weights(
    shape: tuple[int, int], cx: float, cy: float, diameter: float, *, hardness: float
) -> tuple[slice, slice, np.ndarray] | None:
    """Pegada redonda do pincel: (linhas, colunas, pesos 0..1) recortada na imagem.

    ``hardness`` 1 = borda dura (só antialias de 1 px); 0 = queda suave até a borda.
    """
    h, w = shape[:2]
    r = max(0.5, float(diameter) / 2.0)
    x0, x1 = max(0, int(np.floor(cx - r))), min(w, int(np.ceil(cx + r)) + 1)
    y0, y1 = max(0, int(np.floor(cy - r))), min(h, int(np.ceil(cy + r)) + 1)
    if x0 >= x1 or y0 >= y1:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    dist = np.hypot(xx - cx, yy - cy)
    edge = np.clip(r - dist + 0.5, 0.0, 1.0)
    if hardness < 1.0:
        core = r * float(np.clip(hardness, 0.0, 0.99))
        t = np.clip((r - dist) / max(r - core, 1e-3), 0.0, 1.0)
        edge = np.minimum(edge, t * t * (3.0 - 2.0 * t))
    if not edge.any():
        return None
    return slice(y0, y1), slice(x0, x1), edge.astype(np.float32)


def range_weights(values: np.ndarray, value_range: SaturationRange) -> np.ndarray:
    """Quanto cada densidade é afetada: Low = tons claros, Mid = médios, High = escuros."""
    v = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0)
    if value_range == "high":
        w = (v - 0.3) / 0.45
    elif value_range == "mid":
        w = 1.0 - np.abs(v - 0.5) / 0.4
    else:
        w = (0.7 - v) / 0.45
    return np.clip(w, 0.0, 1.0).astype(np.float32)


def saturate_dab(raw: np.ndarray, rows: slice, cols: slice, weights: np.ndarray, flow: float,
                 *, desaturate: bool, value_range: SaturationRange = DEFAULT_RANGE) -> bool:
    """Saturate: mais tinta onde já há tinta; Desaturate: menos tinta. Altera ``raw``."""
    region = raw[rows, cols]
    k = np.clip(float(flow), 0.0, 1.0) * weights * range_weights(region, value_range)
    if desaturate:
        new = region * (1.0 - k)
    else:
        new = np.where(region > INK_EPS, region + k * (1.0 - region), region)
    if np.array_equal(new, region):
        return False
    raw[rows, cols] = new
    return True


def erase_dab(raw: np.ndarray, rows: slice, cols: slice, weights: np.ndarray) -> bool:
    """Borracha: leva a tinta a zero sob o pincel. Altera ``raw``."""
    region = raw[rows, cols]
    if not (region > 0).any():
        return False
    raw[rows, cols] = region * (1.0 - weights)
    return True


def segment_points(p0: tuple[float, float], p1: tuple[float, float], spacing: float) -> list[tuple[float, float]]:
    """Pontos de carimbo de p0 (exclusivo) até p1 (inclusivo), espaçados de ``spacing``."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    n = max(1, int(np.ceil(np.hypot(dx, dy) / max(spacing, 0.5))))
    return [(p0[0] + dx * i / n, p0[1] + dy * i / n) for i in range(1, n + 1)]


@dataclass
class BrushStroke:
    """Um traço de Saturate/Desaturate/Eraser sobre as separações ativas (cópias de trabalho)."""

    tool: BrushTool
    working: dict[str, np.ndarray]
    diameter: float = DEFAULT_BRUSH_DIAMETER
    hardness: float = DEFAULT_HARDNESS
    flow: float = DEFAULT_FLOW
    value_range: SaturationRange = DEFAULT_RANGE
    touched: set[str] = field(default_factory=set)
    dirty: set[str] = field(default_factory=set)
    last: tuple[float, float] | None = None

    @classmethod
    def start(cls, tool: BrushTool, channels: list[ChannelInfo], target_ids, **kwargs) -> BrushStroke:
        ids = set(target_ids)
        working = {ch.id: source_mask(ch).copy() for ch in channels if ch.id in ids and ch.mask is not None}
        return cls(tool, working, **kwargs)

    def _dab(self, x: float, y: float) -> None:
        for cid, raw in self.working.items():
            hit = brush_weights(raw.shape, x, y, self.diameter, hardness=self.hardness)
            if hit is None:
                continue
            rows, cols, weights = hit
            if self.tool == "eraser":
                changed = erase_dab(raw, rows, cols, weights)
            else:
                changed = saturate_dab(raw, rows, cols, weights, self.flow,
                                       desaturate=self.tool == "desaturate", value_range=self.value_range)
            if changed:
                self.touched.add(cid)
                self.dirty.add(cid)

    def press(self, x: float, y: float) -> None:
        self.last = (float(x), float(y))
        self._dab(*self.last)

    def move_to(self, x: float, y: float) -> None:
        if self.last is None:
            self.press(x, y)
            return
        for px, py in segment_points(self.last, (float(x), float(y)), self.diameter / 4.0):
            self._dab(px, py)
        self.last = (float(x), float(y))

    def take_dirty(self) -> dict[str, np.ndarray]:
        out = {cid: self.working[cid] for cid in self.dirty}
        self.dirty = set()
        return out


# ------------------------------------------------------------------ seleção

def erase_selection(channels: list[ChannelInfo], target_ids, selection: np.ndarray) -> SeparationEdit:
    """Edit > Delete: tira a tinta das separações-alvo dentro da seleção (0..1, com Feather)."""
    ids = set(target_ids)
    sel = np.clip(np.asarray(selection, dtype=np.float32), 0.0, 1.0)
    out: list[ChannelInfo] = []
    changed: set[str] = set()
    for ch in channels:
        if ch.id in ids and ch.mask is not None and ch.mask.shape == sel.shape:
            raw = source_mask(ch)
            if (raw * sel > 0).any():
                out.append(_with_raw(ch, raw * (1.0 - sel)))
                changed.add(ch.id)
                continue
        out.append(ch)
    return SeparationEdit(out, changed=changed,
                          message=f"Deleted selection in {len(changed)} separation(s).")
