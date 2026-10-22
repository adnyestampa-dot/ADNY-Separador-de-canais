"""Exportação raster 1:1 de filmes preto-no-branco em PDF multipágina."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from collections.abc import Callable
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from packages.prepress.models import FilmConfig
from packages.prepress.operations import PrepressPlate, mm_to_pixels


def _registration_mark(
    draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int, width: int
) -> None:
    x, y = center
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=0, width=width)
    draw.line((x - radius * 2, y, x + radius * 2, y), fill=0, width=width)
    draw.line((x, y - radius * 2, x, y + radius * 2), fill=0, width=width)


def render_film_page(plate: PrepressPlate, config: FilmConfig) -> Image.Image:
    """Renderiza uma página no mesmo DPI da chapa; pixels não são redimensionados."""
    mask = np.clip(np.asarray(plate.mask, dtype=np.float32), 0, 1)
    height, width = mask.shape
    margin = mm_to_pixels(config.margin_mm, config.dpi)
    page = Image.new("L", (width + 2 * margin, height + 2 * margin), 255)
    film = Image.fromarray(np.rint((1.0 - mask) * 255.0).astype(np.uint8), mode="L")
    page.paste(film, (margin, margin))
    draw = ImageDraw.Draw(page)
    stroke = max(1, int(round(config.dpi / 300)))
    mark = max(3, mm_to_pixels(2.0, config.dpi))
    gap = max(2, mm_to_pixels(1.5, config.dpi))
    if config.crop_marks and margin:
        left, top, right, bottom = margin, margin, margin + width, margin + height
        draw.line((left - gap - mark, top, left - gap, top), fill=0, width=stroke)
        draw.line((left, top - gap - mark, left, top - gap), fill=0, width=stroke)
        draw.line((right + gap, top, right + gap + mark, top), fill=0, width=stroke)
        draw.line((right, top - gap - mark, right, top - gap), fill=0, width=stroke)
        draw.line((left - gap - mark, bottom, left - gap, bottom), fill=0, width=stroke)
        draw.line((left, bottom + gap, left, bottom + gap + mark), fill=0, width=stroke)
        draw.line((right + gap, bottom, right + gap + mark, bottom), fill=0, width=stroke)
        draw.line((right, bottom + gap, right, bottom + gap + mark), fill=0, width=stroke)
    if config.registration_marks and margin >= mark * 2:
        centers = (
            (margin // 2, margin // 2),
            (page.width - margin // 2, margin // 2),
            (margin // 2, page.height - margin // 2),
            (page.width - margin // 2, page.height - margin // 2),
        )
        for center in centers:
            _registration_mark(draw, center, mark // 2, stroke)
    if config.label and margin:
        label = f"{plate.export_name} | {config.dpi:g} DPI | {width}x{height} px"
        draw.text((margin, max(0, margin // 4)), label, fill=0, font=ImageFont.load_default())
    page.info["dpi"] = (config.dpi, config.dpi)
    return page


def export_films_pdf(
    plates: Sequence[PrepressPlate],
    path: str | Path,
    config: FilmConfig,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Grava uma página por chapa com substituição atômica no destino."""
    if not plates:
        raise ValueError("Nenhuma chapa para exportar.")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    pages: list[Image.Image] = []
    for plate in plates:
        if cancelled is not None and cancelled():
            raise RuntimeError("Exportação PDF cancelada.")
        pages.append(render_film_page(plate, config).convert("RGB"))
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=".pdf.tmp", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        pages[0].save(
            temporary,
            format="PDF",
            save_all=True,
            append_images=pages[1:],
            resolution=config.dpi,
            title="Filmes FAV8+",
            producer="ADNY Separador",
        )
        if cancelled is not None and cancelled():
            raise RuntimeError("Exportação PDF cancelada.")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def manifest_path_for(pdf_path: str | Path) -> Path:
    return Path(pdf_path).with_suffix(".manifest.json")


def write_manifest_atomic(
    pdf_path: str | Path, manifest: Mapping[str, Any]
) -> Path:
    """Serializa UTF-8 determinístico e troca o JSON lateral atomicamente."""
    output = manifest_path_for(pdf_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=".json.tmp", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output
