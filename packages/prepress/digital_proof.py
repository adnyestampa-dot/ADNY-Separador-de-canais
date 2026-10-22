"""Simulação digital não calibrada, em memória, do pipeline de filmes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

import numpy as np
from PIL import Image

from packages.prepress.models import PrepressConfig
from packages.prepress.operations import PrepressPlate
from packages.prepress.pipeline import prepare_plates

ProofMode: TypeAlias = Literal[
    "composite",
    "plate",
    "key",
    "underbase",
    "top_white",
    "trapping_knockout",
    "screening",
]

DIGITAL_PROOF_LABEL = "Simulação digital — não calibrada"


class DigitalProofCancelled(RuntimeError):
    """O preview deixou de ser relevante antes de terminar."""


@dataclass(frozen=True, slots=True)
class DigitalProof:
    image: Image.Image
    plates: tuple[PrepressPlate, ...]
    mode: ProofMode
    selected_plate: str | None
    classification: str = "digital_unmeasured"
    label: str = DIGITAL_PROOF_LABEL


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise DigitalProofCancelled("Preview digital cancelado.")


def _find_plate(
    plates: Sequence[PrepressPlate], mode: ProofMode, selected_plate: str | None
) -> PrepressPlate | None:
    if mode in {"plate", "screening"}:
        return next(
            (
                plate
                for plate in plates
                if selected_plate in {plate.key, plate.export_name}
            ),
            plates[0] if plates else None,
        )
    role = {"key": "key", "underbase": "underbase", "top_white": "highlight"}.get(mode)
    return next((plate for plate in plates if plate.role == role), None)


def _composite(plates: Sequence[PrepressPlate]) -> np.ndarray:
    shape = plates[0].mask.shape
    rgb = np.full((*shape, 3), 255.0, dtype=np.float32)
    for plate in plates:
        mask = np.clip(np.asarray(plate.mask, dtype=np.float32), 0, 1)[..., None]
        ink = np.asarray(plate.color_rgb, dtype=np.float32)
        rgb = rgb * (1.0 - mask) + ink * mask
    return np.rint(np.clip(rgb, 0, 255)).astype(np.uint8)


def _change_map(
    source: Sequence[PrepressPlate], prepared: Sequence[PrepressPlate]
) -> np.ndarray:
    shape = prepared[0].mask.shape
    before = {plate.key: np.asarray(plate.mask, dtype=np.float32) for plate in source}
    changed = np.zeros(shape, dtype=bool)
    occupancy = np.zeros(shape, dtype=np.uint16)
    for plate in prepared:
        mask = np.asarray(plate.mask, dtype=np.float32)
        occupancy += mask > 0
        original = before.get(plate.key)
        changed |= original is None or np.abs(mask - original) > 1e-6
    image = np.full((*shape, 3), 245, dtype=np.uint8)
    image[occupancy > 1] = (30, 100, 230)
    image[changed] = (235, 45, 45)
    image[changed & (occupancy > 1)] = (190, 40, 200)
    return image


def render_digital_proof(
    plates: Sequence[PrepressPlate],
    config: PrepressConfig,
    *,
    dpi: float,
    alpha: np.ndarray | None = None,
    mode: ProofMode = "composite",
    selected_plate: str | None = None,
    max_size: tuple[int, int] | None = (1200, 1200),
    pixel_zoom: int = 1,
    cancelled: Callable[[], bool] | None = None,
) -> DigitalProof:
    """Renderiza sem I/O e sem alterar as máscaras de entrada.

    A preparação é deliberadamente a mesma usada pelo PDF: ``prepare_plates`` com
    a mesma instância de ``PrepressConfig`` e o mesmo DPI/alpha. A redução ocorre
    somente depois do pipeline.
    """
    if mode not in {
        "composite",
        "plate",
        "key",
        "underbase",
        "top_white",
        "trapping_knockout",
        "screening",
    }:
        raise ValueError(f"Modo de prova digital inválido: {mode}")
    if pixel_zoom < 1:
        raise ValueError("pixel_zoom deve ser positivo.")
    source = tuple(plates)
    _check_cancelled(cancelled)
    prepared = prepare_plates(source, config, dpi=dpi, alpha=alpha)
    _check_cancelled(cancelled)
    if not prepared:
        raise ValueError("Nenhuma chapa para simular.")

    selected = _find_plate(prepared, mode, selected_plate)
    if mode == "composite":
        array = _composite(prepared)
    elif mode == "trapping_knockout":
        array = _change_map(source, prepared)
    else:
        mask = (
            np.asarray(selected.mask, dtype=np.float32)
            if selected is not None
            else np.zeros(prepared[0].mask.shape, dtype=np.float32)
        )
        gray = np.rint(np.clip(mask, 0, 1) * 255).astype(np.uint8)
        array = np.repeat(gray[..., None], 3, axis=2)

    image = Image.fromarray(array, "RGB")
    if mode == "screening" and pixel_zoom > 1:
        image = image.resize(
            (image.width * pixel_zoom, image.height * pixel_zoom),
            Image.Resampling.NEAREST,
        )
    if max_size is not None:
        image.thumbnail(max_size, Image.Resampling.NEAREST)
    _check_cancelled(cancelled)
    return DigitalProof(
        image=image,
        plates=prepared,
        mode=mode,
        selected_plate=selected.key if selected is not None else None,
    )
