"""Composição explícita das transformações de pré-impressão."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import numpy.typing as npt

from packages.prepress.models import PrepressConfig
from packages.prepress.operations import (
    PrepressPlate,
    apply_overprint,
    joint_cleanup_masks,
    make_white_plates,
    screen_plates,
    trap_plates,
    union_masks,
)


@dataclass(frozen=True, slots=True)
class PrepressResult:
    plates: tuple[PrepressPlate, ...]
    diagnostics: dict[str, Any]


def _white_kind(plate: PrepressPlate) -> str | None:
    identity = {plate.key.casefold(), plate.export_name.casefold()}
    if plate.role == "underbase" or identity & {"underbase", "base_white", "prepress_underbase"}:
        return "underbase"
    if plate.role == "highlight" or identity & {
        "top_white",
        "highlight_white",
        "prepress_top_white",
    }:
        return "top_white"
    return None


def _desired_whites(mode: str) -> tuple[str, ...]:
    return {
        "off": (),
        "underbase": ("underbase",),
        "top_white": ("top_white",),
        "both": ("underbase", "top_white"),
    }[mode]


def _angle_diagnostics(
    plates: Sequence[PrepressPlate], config: PrepressConfig
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    effective = [
        {
            "channel": plate.key,
            "role": plate.role,
            "angle": config.screening.angle_for(plate.key, plate.role),
            "source": (
                "channel"
                if plate.key in config.screening.angles_by_channel
                else "role"
                if plate.role in config.screening.angles_by_role
                else "default"
            ),
        }
        for plate in plates
    ]
    collisions: list[dict[str, Any]] = []
    for index, first in enumerate(effective):
        for second in effective[index + 1 :]:
            if abs(float(first["angle"]) - float(second["angle"])) < 1e-9:
                collisions.append(
                    {
                        "angle": first["angle"],
                        "channels": [first["channel"], second["channel"]],
                    }
                )
    return effective, collisions


def prepare_plates_with_diagnostics(
    plates: Sequence[PrepressPlate],
    config: PrepressConfig,
    *,
    dpi: float,
    alpha: npt.ArrayLike | None = None,
) -> PrepressResult:
    """Executa o pipeline e registra todas as decisões efetivas."""
    source = tuple(plates)
    if not source:
        return PrepressResult((), {"enabled": config.enabled, "order": []})
    shapes = {plate.mask.shape for plate in source}
    if len(shapes) != 1:
        raise ValueError("Todas as chapas de prepress devem ter a mesma dimensão.")
    shape = source[0].mask.shape
    if alpha is not None:
        alpha_value = np.asarray(alpha, dtype=np.float32)
        if alpha_value.ndim != 2 or alpha_value.shape != shape or not np.isfinite(alpha_value).all():
            raise ValueError("Alpha e chapas de prepress devem ter a mesma dimensão.")
    if not config.enabled:
        return PrepressResult(
            source,
            {
                "enabled": False,
                "curves": {"enabled": False},
                "whites": {"mode": "off", "policy": config.white.policy},
                "trap": {"enabled": False},
                "order": [plate.key for plate in source],
                "overprint": {"enabled": False},
                "angles": [],
                "angle_collisions": [],
                "screening": {"mode": "none"},
            },
        )
    safe_alpha = (
        np.clip(np.asarray(alpha, dtype=np.float32), 0, 1)
        if alpha is not None
        else union_masks(plate.mask for plate in source)
    )
    cleaned_masks, cleanup_report = joint_cleanup_masks(
        tuple(plate.mask for plate in source),
        config.joint_cleanup,
        alpha=safe_alpha,
        dpi=dpi,
        lpi=config.screening.lpi,
    )
    cleaned = tuple(
        PrepressPlate(
            key=plate.key,
            label=plate.label,
            color_rgb=plate.color_rgb,
            mask=mask,
            role=plate.role,
            export_name=plate.export_name,
        )
        for plate, mask in zip(source, cleaned_masks, strict=True)
    )

    desired = _desired_whites(config.white.mode)
    existing = {kind for plate in cleaned if (kind := _white_kind(plate))}
    replaced: list[str] = []
    if config.white.policy == "replace_existing":
        replaced = [kind for kind in desired if kind in existing]
        base = tuple(plate for plate in cleaned if _white_kind(plate) not in desired)
        missing = desired
    else:
        base = cleaned
        missing = tuple(kind for kind in desired if kind not in existing)
    generated: list[PrepressPlate] = []
    for kind in missing:
        mode_config = type(config.white)(
            mode=kind,
            policy=config.white.policy,
            choke_mm=config.white.choke_mm,
            min_density=config.white.min_density,
        )
        generated.extend(make_white_plates(base, mode_config, dpi, safe_alpha))
    underbase = tuple(plate for plate in generated if _white_kind(plate) == "underbase")
    top_white = tuple(plate for plate in generated if _white_kind(plate) == "top_white")
    prepared = underbase + base + top_white
    prepared = trap_plates(prepared, config.trapping, dpi, safe_alpha)
    prepared = apply_overprint(prepared, config.overprint, dpi, safe_alpha)
    prepared = screen_plates(prepared, config.screening, dpi, config.tone_curve)
    angles, collisions = _angle_diagnostics(prepared, config)
    diagnostics: dict[str, Any] = {
        "enabled": True,
        "joint_cleanup": cleanup_report.to_dict(),
        "curves": {
            "enabled": config.tone_curve.enabled,
            "gamma": config.tone_curve.gamma,
            "gain": config.tone_curve.gain,
            "min": config.tone_curve.min_value,
            "max": config.tone_curve.max_value,
        },
        "whites": {
            "mode": config.white.mode,
            "policy": config.white.policy,
            "existing": sorted(existing),
            "generated": [plate.key for plate in generated],
            "replaced": replaced,
        },
        "trap": {
            "enabled": config.trapping.enabled,
            "spread_mm": config.trapping.spread_mm,
            "roles": list(config.trapping.roles),
        },
        "order": [plate.key for plate in prepared],
        "overprint": {
            "enabled": config.overprint.enabled,
            "mode": config.overprint.mode,
            "reach_mm": config.overprint.reach_mm,
        },
        "angles": angles,
        "angle_collisions": collisions,
        "screening": {
            "mode": config.screening.mode,
            "lpi": config.screening.lpi,
            "fm_dot_um": config.screening.fm_dot_um,
            "seed": config.screening.seed,
        },
    }
    return PrepressResult(prepared, diagnostics)


def prepare_plates(
    plates: Sequence[PrepressPlate],
    config: PrepressConfig,
    *,
    dpi: float,
    alpha: npt.ArrayLike | None = None,
) -> tuple[PrepressPlate, ...]:
    """Executa a camada opcional sem modificar as chapas de entrada."""
    return prepare_plates_with_diagnostics(
        plates, config, dpi=dpi, alpha=alpha
    ).plates
