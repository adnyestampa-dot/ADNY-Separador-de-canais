from __future__ import annotations

"""Parâmetros FAV8+ calibrados para aproximar Spot Process (preset legado ss4)."""

from typing import Any


def spot_process_ss4_params(
    *,
    textile_dark: bool = True,
    ink_library_snapshot: dict | None = None,
) -> dict[str, Any]:
    """
    SS4 abre raster → separação Spot Process automática (ordem de pressa, neutros, key).
    Motor: FAV8+ com tuning conservador tipo sim-process comercial.
    """
    params: dict[str, Any] = {
        "engine": "fav8_plus",
        "mode": "default",
        "dark_fabric": textile_dark,
        "key_plate_enabled": True,
        "key_plate_mode": "auto",
        "key_plate_tonal_threshold": 0.36,
        "key_plate_gamma": 0.88,
        "key_plate_chroma_protection": 0.04,
        "key_plate_min_density": 0.0,
        "key_plate_max_density": 1.0,
        "key_plate_merge_compatible_dark": True,
        # cleanup pesado em 4K roda no job; preview usa compositor async
        "joint_cleanup_mode": "auto",
        "joint_cleanup_threshold": 0.032,
        "joint_cleanup_min_area_px": 6,
        "physical_model": "disabled",
        "ss4_spot_process": True,
    }
    if textile_dark:
        # Simulated Process SS4: 9 tintas fixas sobre camiseta preta, sem chapa Black.
        params["sim_process"] = {"enabled": True}
    if ink_library_snapshot is not None:
        params["ink_library_snapshot"] = ink_library_snapshot
    return params
