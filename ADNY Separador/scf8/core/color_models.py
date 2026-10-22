"""Conversões de cor do editor Custom Inks / Custom Textiles (H S B, R G B, L a b, C M Y K).

RGB é sRGB 0..255; HSB em graus/porcentagem; Lab D65 (o mesmo da biblioteca de tintas);
CMYK é a conversão simples sem perfil (porcentagens).
"""

from __future__ import annotations

import colorsys

import numpy as np
from skimage.color import lab2rgb, rgb2lab

RGB = tuple[int, int, int]


def _clamp_rgb(values) -> RGB:
    return tuple(int(round(min(255.0, max(0.0, float(v))))) for v in values)  # type: ignore[return-value]


def rgb_to_hsb(rgb: RGB) -> tuple[float, float, float]:
    h, s, v = colorsys.rgb_to_hsv(*(c / 255.0 for c in rgb))
    return h * 360.0, s * 100.0, v * 100.0


def hsb_to_rgb(h: float, s: float, b: float) -> RGB:
    r, g, bl = colorsys.hsv_to_rgb((h % 360.0) / 360.0, s / 100.0, b / 100.0)
    return _clamp_rgb((r * 255.0, g * 255.0, bl * 255.0))


def rgb_to_lab(rgb: RGB) -> tuple[float, float, float]:
    lab = rgb2lab(np.asarray(rgb, dtype=np.float64).reshape(1, 1, 3) / 255.0).reshape(3)
    return float(lab[0]), float(lab[1]), float(lab[2])


def lab_to_rgb(l_: float, a: float, b: float) -> RGB:
    rgb = lab2rgb(np.asarray([l_, a, b], dtype=np.float64).reshape(1, 1, 3)).reshape(3)
    return _clamp_rgb(np.clip(rgb, 0.0, 1.0) * 255.0)


def rgb_to_cmyk(rgb: RGB) -> tuple[float, float, float, float]:
    r, g, b = (c / 255.0 for c in rgb)
    k = 1.0 - max(r, g, b)
    if k >= 1.0:
        return 0.0, 0.0, 0.0, 100.0
    return (
        (1.0 - r - k) / (1.0 - k) * 100.0,
        (1.0 - g - k) / (1.0 - k) * 100.0,
        (1.0 - b - k) / (1.0 - k) * 100.0,
        k * 100.0,
    )


def cmyk_to_rgb(c: float, m: float, y: float, k: float) -> RGB:
    kk = 1.0 - k / 100.0
    return _clamp_rgb((255.0 * (1.0 - c / 100.0) * kk, 255.0 * (1.0 - m / 100.0) * kk, 255.0 * (1.0 - y / 100.0) * kk))


# Quadrado de cor + barra: o componente marcado no rádio vai na barra, os outros dois no quadrado.
# modo → (modelo, índice da barra, índice do eixo x, índice do eixo y invertido)
PICKER_MODES: dict[str, tuple[str, int, int, int]] = {
    "H": ("hsb", 0, 1, 2), "S": ("hsb", 1, 0, 2), "Bv": ("hsb", 2, 0, 1),
    "L": ("lab", 0, 1, 2), "a": ("lab", 1, 2, 0), "bl": ("lab", 2, 1, 0),
    "R": ("rgb", 0, 2, 1), "G": ("rgb", 1, 2, 0), "Bc": ("rgb", 2, 0, 1),
}
_RANGES = {"hsb": ((0.0, 360.0), (0.0, 100.0), (0.0, 100.0)),
           "lab": ((0.0, 100.0), (-128.0, 127.0), (-128.0, 127.0)),
           "rgb": ((0.0, 255.0), (0.0, 255.0), (0.0, 255.0))}


def model_values(model: str, rgb: RGB) -> tuple[float, float, float]:
    if model == "hsb":
        return rgb_to_hsb(rgb)
    if model == "lab":
        return rgb_to_lab(rgb)
    return tuple(float(c) for c in rgb)  # type: ignore[return-value]


def _model_to_rgb_array(model: str, values: np.ndarray) -> np.ndarray:
    """``values`` (..., 3) no modelo → RGB float 0..1."""
    if model == "rgb":
        return np.clip(values / 255.0, 0.0, 1.0)
    if model == "lab":
        return np.clip(lab2rgb(values), 0.0, 1.0)
    h = (values[..., 0] % 360.0) / 60.0
    s = np.clip(values[..., 1] / 100.0, 0.0, 1.0)
    v = np.clip(values[..., 2] / 100.0, 0.0, 1.0)
    i = np.floor(h).astype(int) % 6
    f = h - np.floor(h)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    choices = [np.stack(c, axis=-1) for c in ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))]
    out = np.zeros(values.shape, dtype=np.float64)
    for k, arr in enumerate(choices):
        out[i == k] = arr[i == k]
    return out


def axis_range(mode: str, which: str) -> tuple[float, float]:
    model, bar, x, y = PICKER_MODES[mode]
    return _RANGES[model][{"bar": bar, "x": x, "y": y}[which]]


def picker_square(mode: str, rgb: RGB, size: int = 128) -> np.ndarray:
    """Imagem (size, size, 3) uint8 do quadrado de cor para o componente da barra fixo."""
    model, bar, x, y = PICKER_MODES[mode]
    base = model_values(model, rgb)
    (x0, x1), (y0, y1) = _RANGES[model][x], _RANGES[model][y]
    xs = np.linspace(x0, x1, size)
    ys = np.linspace(y1, y0, size)
    grid = np.empty((size, size, 3), dtype=np.float64)
    grid[..., bar] = base[bar]
    grid[..., x] = xs[None, :]
    grid[..., y] = ys[:, None]
    return (_model_to_rgb_array(model, grid) * 255.0 + 0.5).astype(np.uint8)


def picker_bar(mode: str, rgb: RGB, length: int = 128) -> np.ndarray:
    """Barra vertical (length, 1, 3) uint8: o componente da barra de cima (máximo) para baixo."""
    model, bar, _x, _y = PICKER_MODES[mode]
    base = np.asarray(model_values(model, rgb), dtype=np.float64)
    lo, hi = _RANGES[model][bar]
    values = np.repeat(base[None, :], length, axis=0)
    values[:, bar] = np.linspace(hi, lo, length)
    if model == "hsb" and bar == 0:
        values[:, 1] = values[:, 2] = 100.0
    return (_model_to_rgb_array(model, values.reshape(length, 1, 3)) * 255.0 + 0.5).astype(np.uint8)


def picker_pick(mode: str, rgb: RGB, *, fx: float | None = None, fy: float | None = None,
                fbar: float | None = None) -> RGB:
    """Cor nova ao clicar no quadrado (fx, fy em 0..1, y de cima para baixo) ou na barra (fbar 0..1)."""
    model, bar, x, y = PICKER_MODES[mode]
    values = list(model_values(model, rgb))
    if fx is not None and fy is not None:
        (x0, x1), (y0, y1) = _RANGES[model][x], _RANGES[model][y]
        values[x] = x0 + min(1.0, max(0.0, fx)) * (x1 - x0)
        values[y] = y1 - min(1.0, max(0.0, fy)) * (y1 - y0)
    if fbar is not None:
        lo, hi = _RANGES[model][bar]
        values[bar] = hi - min(1.0, max(0.0, fbar)) * (hi - lo)
    if model == "hsb":
        return hsb_to_rgb(*values)
    if model == "lab":
        return lab_to_rgb(*values)
    return _clamp_rgb(values)


def picker_marker(mode: str, rgb: RGB) -> tuple[float, float, float]:
    """Posição (fx, fy, fbar) da cor atual no quadrado e na barra (0..1)."""
    model, bar, x, y = PICKER_MODES[mode]
    values = model_values(model, rgb)

    def frac(index: int, invert: bool) -> float:
        lo, hi = _RANGES[model][index]
        f = (values[index] - lo) / (hi - lo)
        f = min(1.0, max(0.0, f))
        return 1.0 - f if invert else f

    return frac(x, False), frac(y, True), frac(bar, True)
