"""Operações puras de preparação de chapas, sem dependência do separador."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from typing import Iterable, Sequence

import numpy as np
import numpy.typing as npt
from scipy import ndimage

from packages.prepress.models import (
    JointCleanupConfig,
    OverprintConfig,
    ScreenConfig,
    ToneCurveConfig,
    TrapConfig,
    WhiteConfig,
)

Mask = npt.NDArray[np.float32]


def _validated_masks(
    masks: Sequence[npt.ArrayLike], operation: str
) -> tuple[tuple[Mask, ...], tuple[int, int] | None]:
    items = tuple(np.asarray(mask, dtype=np.float32) for mask in masks)
    if not items:
        return items, None
    shape = items[0].shape
    if len(shape) != 2 or any(
        item.ndim != 2 or item.shape != shape or not np.isfinite(item).all()
        for item in items
    ):
        raise ValueError(
            f"Todas as máscaras de {operation} devem ser 2D, finitas e ter a mesma dimensão."
        )
    return items, shape


def _validated_alpha(
    alpha: npt.ArrayLike | None,
    shape: tuple[int, int] | None,
    operation: str,
) -> Mask | None:
    if alpha is None:
        return None
    value = np.asarray(alpha, dtype=np.float32)
    if (
        shape is None
        or value.ndim != 2
        or value.shape != shape
        or not np.isfinite(value).all()
    ):
        raise ValueError(f"Alpha e máscaras de {operation} devem ter a mesma dimensão.")
    return np.clip(value, 0, 1).astype(np.float32, copy=False)


@dataclass(frozen=True, slots=True)
class PrepressPlate:
    key: str
    label: str
    color_rgb: tuple[int, int, int]
    mask: Mask
    role: str = "chromatic"
    export_name: str = ""

    def __post_init__(self) -> None:
        mask = np.asarray(self.mask, dtype=np.float32)
        if mask.ndim != 2 or not np.isfinite(mask).all():
            raise ValueError(f"Máscara inválida para a chapa {self.key!r}.")
        frozen = np.clip(mask, 0, 1).astype(np.float32, copy=True)
        frozen.setflags(write=False)
        object.__setattr__(self, "mask", frozen)
        if not self.export_name:
            object.__setattr__(self, "export_name", self.key.upper())


@dataclass(frozen=True, slots=True)
class JointCleanupReport:
    mode: str
    threshold: float
    configured_min_area_px: int
    effective_min_area_px: int
    policy_source: str
    removed_components: int = 0
    removed_pixels: int = 0

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "threshold": self.threshold,
            "configured_min_area_px": self.configured_min_area_px,
            "effective_min_area_px": self.effective_min_area_px,
            "policy_source": self.policy_source,
            "removed_components": self.removed_components,
            "removed_pixels": self.removed_pixels,
        }


def resolve_cleanup_area(
    config: JointCleanupConfig,
    *,
    dpi: float | None = None,
    lpi: float | None = None,
) -> tuple[int, str]:
    """Resolve a área sem apagar pontos de meio-tom válidos por padrão."""
    if config.mode != "auto":
        return config.min_area_px, "manual" if config.mode == "manual" else "off"
    resolved_dpi = config.dpi if config.dpi is not None else dpi
    resolved_lpi = config.lpi if config.lpi is not None else lpi
    if resolved_dpi is None or resolved_lpi is None:
        return config.min_area_px, "fallback"
    # 2% da célula de retícula: remove ruído bem menor que um ponto imprimível,
    # sem confundir pontos isolados do meio-tom com sujeira.
    derived = max(1, int(round(0.02 * (resolved_dpi / resolved_lpi) ** 2)))
    return max(config.min_area_px, derived), "dpi_lpi"


def joint_cleanup_masks(
    masks: Sequence[npt.ArrayLike],
    config: JointCleanupConfig,
    *,
    alpha: npt.ArrayLike | None = None,
    dpi: float | None = None,
    lpi: float | None = None,
    copy: bool = True,
) -> tuple[tuple[Mask, ...], JointCleanupReport]:
    """Remove componentes pequenos da união e a mesma região de cada canal."""
    items, shape = _validated_masks(masks, "joint cleanup")
    safe_alpha = _validated_alpha(alpha, shape, "joint cleanup")
    effective_area, policy = resolve_cleanup_area(config, dpi=dpi, lpi=lpi)
    base_report = JointCleanupReport(
        config.mode,
        config.threshold,
        config.min_area_px,
        effective_area,
        policy,
    )
    if config.mode == "off" or not items:
        return items, base_report
    assert shape is not None

    # Uma união booleana e um mapa int32 são independentes do número de canais;
    # isso evita empilhar todas as chapas (especialmente caro em imagens 4K).
    foreground = np.zeros(shape, dtype=np.bool_)
    for item in items:
        np.logical_or(foreground, item > config.threshold, out=foreground)
    labels, component_count = ndimage.label(
        foreground,
        structure=np.ones((3, 3), dtype=np.uint8),
    )
    del foreground
    areas = np.bincount(labels.ravel())
    small = areas < effective_area
    small[0] = False
    if config.mode == "auto" and component_count >= 16:
        # Pontos de meio-tom aparecem como muitos componentes repetidos com a
        # mesma área. Preservá-los evita transformar retícula legítima em ruído.
        area_values, frequency = np.unique(areas[1:], return_counts=True)
        repeated = {
            int(area)
            for area, count in zip(area_values, frequency, strict=True)
            if count >= 16
        }
        if repeated and int(max(frequency)) >= math.ceil(component_count * 0.5):
            small[np.isin(areas, tuple(repeated))] = False
            policy = f"{policy}_halftone_guard"
            base_report = replace(base_report, policy_source=policy)
    removed_components = int(np.count_nonzero(small))
    if removed_components:
        remove = small[labels]
        removed_pixels = int(np.count_nonzero(remove))
    else:
        remove = None
        removed_pixels = 0
    del labels, areas, small

    output: list[Mask] = []
    for item in items:
        if copy:
            cleaned = np.clip(item, 0, 1).astype(np.float32, copy=True)
        else:
            if item.dtype != np.float32 or not item.flags.writeable:
                raise ValueError("copy=False requer máscaras float32 graváveis.")
            cleaned = item
            np.clip(cleaned, 0, 1, out=cleaned)
        if remove is not None:
            cleaned[remove] = 0.0
        if safe_alpha is not None:
            np.minimum(cleaned, safe_alpha, out=cleaned)
        output.append(cleaned)
    return tuple(output), replace(
        base_report,
        removed_components=removed_components,
        removed_pixels=removed_pixels,
    )


def mm_to_pixels(mm: float, dpi: float) -> int:
    """Converte unidade física em raio inteiro; medida positiva nunca desaparece."""
    if mm < 0 or dpi <= 0:
        raise ValueError("mm deve ser não negativo e dpi deve ser positivo.")
    return 0 if mm == 0 else max(1, int(math.ceil(mm * dpi / 25.4)))


def _footprint(radius: int) -> npt.NDArray[np.bool_]:
    y, x = np.ogrid[-radius : radius + 1, -radius : radius + 1]
    return (x * x + y * y) <= radius * radius


def _dilate(mask: npt.ArrayLike, radius: int) -> Mask:
    source = np.asarray(mask, dtype=np.float32)
    if radius == 0:
        return source.copy()
    return ndimage.grey_dilation(source, footprint=_footprint(radius)).astype(np.float32)


def _erode(mask: npt.ArrayLike, radius: int) -> Mask:
    source = np.asarray(mask, dtype=np.float32)
    if radius == 0:
        return source.copy()
    return ndimage.grey_erosion(source, footprint=_footprint(radius)).astype(np.float32)


def union_masks(masks: Iterable[npt.ArrayLike], shape: tuple[int, int] | None = None) -> Mask:
    items = [np.asarray(mask, dtype=np.float32) for mask in masks]
    if not items:
        if shape is None:
            raise ValueError("shape é obrigatório para uma união vazia.")
        return np.zeros(shape, dtype=np.float32)
    result = np.maximum.reduce(items)
    return np.clip(result, 0, 1).astype(np.float32)


def make_white_plates(
    plates: Sequence[PrepressPlate],
    config: WhiteConfig,
    dpi: float,
    alpha: npt.ArrayLike | None = None,
) -> tuple[PrepressPlate, ...]:
    """Cria underbase/top-white a partir da união; choke encolhe, nunca expande."""
    masks, shape = _validated_masks(tuple(plate.mask for plate in plates), "brancos")
    alpha_mask = _validated_alpha(alpha, shape, "brancos")
    if config.mode == "off" or not plates:
        return ()
    source = [
        plate.mask
        for plate in plates
        if plate.role not in {"underbase", "highlight"} and plate.key not in {"base_white", "highlight_white"}
    ]
    if not source:
        source = [plate.mask for plate in plates]
    mask = union_masks(source)
    mask[mask < config.min_density] = 0
    mask = _erode(mask, mm_to_pixels(config.choke_mm, dpi))
    if alpha_mask is not None:
        mask = np.minimum(mask, alpha_mask)
    output: list[PrepressPlate] = []
    if config.mode in {"underbase", "both"}:
        output.append(
            PrepressPlate(
                "prepress_underbase",
                "Underbase",
                (255, 255, 255),
                mask,
                "underbase",
                "UNDERBASE",
            )
        )
    if config.mode in {"top_white", "both"}:
        output.append(
            PrepressPlate(
                "prepress_top_white",
                "Top White",
                (255, 255, 255),
                mask,
                "highlight",
                "TOP_WHITE",
            )
        )
    return tuple(output)


def _luminance(rgb: tuple[int, int, int]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def trap_plates(
    plates: Sequence[PrepressPlate],
    config: TrapConfig,
    dpi: float,
    alpha: npt.ArrayLike | None = None,
) -> tuple[PrepressPlate, ...]:
    """Espalha a chapa clara sob a escura nas vizinhanças de contato."""
    _, shape = _validated_masks(tuple(plate.mask for plate in plates), "trapping")
    alpha_mask = _validated_alpha(alpha, shape, "trapping")
    if not config.enabled or config.spread_mm == 0:
        return tuple(plates)
    radius = mm_to_pixels(config.spread_mm, dpi)
    masks = [plate.mask.copy() for plate in plates]
    eligible = [i for i, plate in enumerate(plates) if plate.role in config.roles]
    for pos, first_index in enumerate(eligible):
        for second_index in eligible[pos + 1 :]:
            first, second = plates[first_index], plates[second_index]
            if _luminance(first.color_rgb) <= _luminance(second.color_rgb):
                dark_index, light_index = first_index, second_index
            else:
                dark_index, light_index = second_index, first_index
            dark_near = _dilate(masks[dark_index], radius)
            spread = np.minimum(_dilate(masks[light_index], radius), dark_near)
            masks[light_index] = np.maximum(masks[light_index], spread)
    if alpha_mask is not None:
        masks = [np.minimum(mask, alpha_mask) for mask in masks]
    return tuple(replace(plate, mask=mask) for plate, mask in zip(plates, masks, strict=True))


def apply_overprint(
    plates: Sequence[PrepressPlate],
    config: OverprintConfig,
    dpi: float,
    alpha: npt.ArrayLike | None = None,
) -> tuple[PrepressPlate, ...]:
    """Aplica knockout por ordem de impressão ou build-up com alcance físico."""
    _, shape = _validated_masks(tuple(plate.mask for plate in plates), "overprint")
    alpha_mask = _validated_alpha(alpha, shape, "overprint")
    if not config.enabled or not plates:
        return tuple(plates)
    masks = [plate.mask.copy() for plate in plates]
    if config.mode == "knockout":
        occupied = np.zeros_like(masks[0])
        for index in range(len(masks) - 1, -1, -1):
            current = masks[index]
            masks[index] = current * (1.0 - occupied)
            occupied = np.maximum(occupied, current)
    else:
        radius = mm_to_pixels(config.reach_mm, dpi)
        if radius:
            masks = [_dilate(mask, radius) for mask in masks]
    if alpha_mask is not None:
        masks = [np.minimum(mask, alpha_mask) for mask in masks]
    return tuple(replace(plate, mask=mask) for plate, mask in zip(plates, masks, strict=True))


def gap_count(
    reference: Sequence[PrepressPlate],
    processed: Sequence[PrepressPlate],
    threshold: float = 1e-6,
) -> int:
    """Conta pixels antes cobertos que ficaram sem nenhuma tinta."""
    if not reference:
        return 0
    before = union_masks(plate.mask for plate in reference)
    after = union_masks((plate.mask for plate in processed), before.shape)
    return int(np.count_nonzero((before > threshold) & (after <= threshold)))


def apply_tone_curve(mask: npt.ArrayLike, config: ToneCurveConfig) -> Mask:
    """Aplica gamma/gain/limites; desativada é identidade bit a bit."""
    source = np.asarray(mask)
    if source.ndim != 2 or not np.isfinite(source).all():
        raise ValueError("Máscara da curva tonal deve ser 2D e finita.")
    if not config.enabled:
        return source.astype(np.float32, copy=True)
    source = np.clip(np.asarray(mask, dtype=np.float32), 0, 1)
    curved = np.power(source, config.gamma)
    curved += config.gain * 4.0 * curved * (1.0 - curved)
    curved = np.clip(curved, 0, 1)
    positive = curved > 0
    curved[positive] = np.clip(
        curved[positive], config.min_value, config.max_value
    )
    curved[source >= 1.0] = 1.0
    return curved.astype(np.float32)


def screen_mask(
    mask: npt.ArrayLike,
    config: ScreenConfig,
    dpi: float,
    *,
    channel_key: str = "",
    role: str = "chromatic",
    tone_curve: ToneCurveConfig | None = None,
) -> Mask:
    """Retícula AM geométrica ou FM estocástica reproduzível em resolução 1:1."""
    tone = apply_tone_curve(mask, tone_curve or ToneCurveConfig())
    if config.mode == "none":
        return tone
    height, width = tone.shape
    if config.mode == "am":
        cell = max(2.0, dpi / config.lpi)
        angle = math.radians(config.angle_for(channel_key, role))
        yy, xx = np.indices((height, width), dtype=np.float32)
        u = (xx * math.cos(angle) + yy * math.sin(angle)) % cell
        v = (-xx * math.sin(angle) + yy * math.cos(angle)) % cell
        dx = np.minimum(u, cell - u) / (cell * 0.5)
        dy = np.minimum(v, cell - v) / (cell * 0.5)
        threshold = np.clip((dx * dx + dy * dy) * (math.pi / 4.0), 0, 1)
        screened = tone >= threshold
        screened[tone <= 0.0] = False
        screened[tone >= 1.0] = True
        return screened.astype(np.float32)
    dot_px = max(1, int(round(config.fm_dot_um * dpi / 25_400.0)))
    grid_h = math.ceil(height / dot_px)
    grid_w = math.ceil(width / dot_px)
    salt = int.from_bytes(hashlib.sha256(channel_key.encode("utf-8")).digest()[:8], "little")
    rng = np.random.default_rng((config.seed + salt) % (2**64))
    thresholds = rng.random((grid_h, grid_w), dtype=np.float32)
    threshold_map = np.repeat(np.repeat(thresholds, dot_px, axis=0), dot_px, axis=1)
    screened = tone >= threshold_map[:height, :width]
    screened[tone <= 0.0] = False
    screened[tone >= 1.0] = True
    return screened.astype(np.float32)


def screen_plates(
    plates: Sequence[PrepressPlate],
    config: ScreenConfig,
    dpi: float,
    tone_curve: ToneCurveConfig | None = None,
) -> tuple[PrepressPlate, ...]:
    _, _ = _validated_masks(tuple(plate.mask for plate in plates), "screening")
    curve = tone_curve or ToneCurveConfig()
    if config.mode == "none" and not curve.enabled:
        return tuple(plates)
    return tuple(
        replace(
            plate,
            mask=screen_mask(
                plate.mask,
                config,
                dpi,
                channel_key=plate.key,
                role=plate.role,
                tone_curve=curve,
            ),
        )
        for plate in plates
    )
