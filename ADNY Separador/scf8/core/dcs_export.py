"""File > Export...: DCS 2.0 EPS de arquivo único (Adobe Technical Note #5044).

O arquivo principal é um EPS com o composite (RGB) e, nos comentários, as cores spot
(``%%DocumentCustomColors``, ``%%CMYKCustomColor``) e uma linha ``%%PlateFile`` por separação
apontando (deslocamento e tamanho em bytes) para a placa anexada depois do ``%%EOF``.
Cada placa é um EPS em tons de cinza 8 bits: preto = 100% de tinta.
"""

from __future__ import annotations

import base64
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from scf8.core.color_models import rgb_to_cmyk

_OFFSET_DIGITS = 10


@dataclass(frozen=True)
class DcsPlate:
    name: str
    coverage: np.ndarray  # (h, w) 0..1: tinta da separação
    rgb: tuple[int, int, int]


def _ps_string(text: str) -> str:
    safe = text.encode("latin-1", errors="replace").decode("latin-1")
    return "(" + safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def _a85(data: bytes) -> str:
    return base64.a85encode(zlib.compress(data, 6), wrapcol=76).decode("ascii") + "~>\n"


def _bbox(width: int, height: int, dpi: float) -> tuple[float, float]:
    scale = 72.0 / max(float(dpi), 1.0)
    return width * scale, height * scale


def _bbox_comments(w_pt: float, h_pt: float) -> str:
    return (
        f"%%BoundingBox: 0 0 {int(np.ceil(w_pt))} {int(np.ceil(h_pt))}\n"
        f"%%HiResBoundingBox: 0 0 {w_pt:.4f} {h_pt:.4f}\n"
    )


def _plate_eps(plate: DcsPlate, w_pt: float, h_pt: float, title: str) -> bytes:
    cov = np.clip(np.asarray(plate.coverage, dtype=np.float32), 0.0, 1.0)
    h, w = cov.shape[:2]
    samples = (255 - np.round(cov * 255.0)).astype(np.uint8)
    text = (
        "%!PS-Adobe-3.0 EPSF-3.0\n"
        f"%%Title: {_ps_string(title + ' - ' + plate.name)}\n"
        + _bbox_comments(w_pt, h_pt)
        + "%%LanguageLevel: 3\n"
        f"%%PlateColor: {plate.name}\n"
        "%%EndComments\n"
        "gsave\n"
        f"{w_pt:.4f} {h_pt:.4f} scale\n"
        f"{w} {h} 8 [{w} 0 0 -{h} 0 {h}]\n"
        "currentfile /ASCII85Decode filter /FlateDecode filter image\n"
    )
    return (text + _a85(samples.tobytes()) + "grestore\n%%EOF\n").encode("latin-1")


def _composite_body(composite: Image.Image, ground_rgb: tuple[int, int, int], w_pt: float, h_pt: float) -> str:
    image = composite
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        flat = Image.new("RGB", image.size, ground_rgb)
        flat.paste(image, mask=image.split()[-1])
        image = flat
    image = image.convert("RGB")
    w, h = image.size
    return (
        "%%BeginProlog\n%%EndProlog\n"
        "%%Page: 1 1\n"
        "gsave\n"
        f"{w_pt:.4f} {h_pt:.4f} scale\n"
        f"{w} {h} 8 [{w} 0 0 -{h} 0 {h}]\n"
        "currentfile /ASCII85Decode filter /FlateDecode filter false 3 colorimage\n"
        + _a85(np.asarray(image, dtype=np.uint8).tobytes())
        + "grestore\n%%Trailer\n%%EOF\n"
    )


def _header(title: str, plates: list[DcsPlate], w_pt: float, h_pt: float, offsets: list[tuple[int, int]]) -> str:
    names = [_ps_string(p.name) for p in plates]
    lines = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        "%%Creator: ADNY Separador (scf8)",
        f"%%Title: {_ps_string(title)}",
        f"%%CreationDate: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        _bbox_comments(w_pt, h_pt).rstrip("\n"),
        "%%LanguageLevel: 3",
        "%%DocumentData: Clean7Bit",
        "%%DocumentProcessColors:",
        "%%DocumentCustomColors: " + (names[0] if names else ""),
        *[f"%%+ {n}" for n in names[1:]],
    ]
    for i, plate in enumerate(plates):
        c, m, y, k = (v / 100.0 for v in rgb_to_cmyk(plate.rgb))
        lines.append(f"{'%%CMYKCustomColor:' if i == 0 else '%%+'} {c:.4f} {m:.4f} {y:.4f} {k:.4f} {names[i]}")
    for i, plate in enumerate(plates):
        r, g, b = (v / 255.0 for v in plate.rgb)
        lines.append(f"{'%%RGBCustomColor:' if i == 0 else '%%+'} {r:.4f} {g:.4f} {b:.4f} {names[i]}")
    for name, (offset, size) in zip(names, offsets):
        lines.append(f"%%PlateFile: {name} EPS #{offset:0{_OFFSET_DIGITS}d} {size:0{_OFFSET_DIGITS}d}")
    lines.append("%%EndComments")
    return "\n".join(lines) + "\n"


def write_dcs2(
    path: str | Path,
    plates: list[DcsPlate],
    composite: Image.Image,
    *,
    dpi: float = 300.0,
    ground_rgb: tuple[int, int, int] = (255, 255, 255),
    title: str = "",
) -> Path:
    """Grava o DCS 2.0 de arquivo único; as placas devem ter o tamanho do composite."""
    if not plates:
        raise ValueError("DCS 2.0 needs at least one separation.")
    w, h = composite.size
    w_pt, h_pt = _bbox(w, h, dpi)
    title = title or Path(path).stem
    body = _composite_body(composite, ground_rgb, w_pt, h_pt).encode("latin-1")
    plate_bytes = [_plate_eps(p, w_pt, h_pt, title) for p in plates]
    head_len = len(_header(title, plates, w_pt, h_pt, [(0, 0)] * len(plates)).encode("latin-1"))
    offsets: list[tuple[int, int]] = []
    cursor = head_len + len(body)
    for data in plate_bytes:
        offsets.append((cursor, len(data)))
        cursor += len(data)
    head = _header(title, plates, w_pt, h_pt, offsets).encode("latin-1")
    if len(head) != head_len:
        raise RuntimeError("DCS 2.0 header size changed while writing the plate offsets.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        handle.write(head)
        handle.write(body)
        for data in plate_bytes:
            handle.write(data)
    return target
