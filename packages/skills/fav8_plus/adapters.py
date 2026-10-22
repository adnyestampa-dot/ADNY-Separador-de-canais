from __future__ import annotations

from typing import Any, cast

import numpy as np
from PIL import Image

from packages.core.models.channel_info import ChannelInfo
from packages.prepress.models import CleanupMode, JointCleanupConfig
from packages.skills.fav8_plus.engine import Fav8Engine
from packages.skills.fav8_plus.loader import fav8_plus_engine_available, fav8_plus_missing_message
from packages.skills.fav8_plus.models import (
    ChannelPlate,
    Fav8Config,
    Fav8Mode,
    KeyPlateConfig,
    KeyPlateMode,
    PhysicalMeasurementProfile,
    SeparationResult,
    SimProcessConfig,
)
from packages.skills.fav8_plus.ink_library import (
    InkLibrarySnapshot,
    default_ink_library,
)


def joint_cleanup_config_from_params(params: dict[str, Any]) -> JointCleanupConfig:
    mode = params.get("joint_cleanup_mode", "off")
    if not isinstance(mode, str):
        raise TypeError("joint_cleanup_mode deve ser uma string.")
    threshold = params.get("joint_cleanup_threshold", 0.03)
    min_area = params.get("joint_cleanup_min_area_px", 4)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise TypeError("joint_cleanup_threshold deve ser numérico.")
    if isinstance(min_area, bool) or not isinstance(min_area, int):
        raise TypeError("joint_cleanup_min_area_px deve ser inteiro.")
    dpi = params.get("joint_cleanup_dpi")
    lpi = params.get("joint_cleanup_lpi")
    for name, value in (("joint_cleanup_dpi", dpi), ("joint_cleanup_lpi", lpi)):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            raise TypeError(f"{name} deve ser numérico ou nulo.")
    return JointCleanupConfig(
        mode=cast(CleanupMode, mode),
        threshold=float(threshold),
        min_area_px=min_area,
        dpi=float(dpi) if dpi is not None else None,
        lpi=float(lpi) if lpi is not None else None,
    )


def key_plate_config_from_params(params: dict[str, Any]) -> KeyPlateConfig:
    mode = params.get("key_plate_mode", "auto")
    if not isinstance(mode, str):
        raise TypeError("key_plate_mode deve ser uma string.")
    enabled = params.get("key_plate_enabled", False)
    merge = params.get("key_plate_merge_compatible_dark", False)
    if not isinstance(enabled, bool):
        raise TypeError("key_plate_enabled deve ser booleano.")
    if not isinstance(merge, bool):
        raise TypeError("key_plate_merge_compatible_dark deve ser booleano.")
    values: dict[str, float] = {}
    for param, field_name, default in (
        ("key_plate_tonal_threshold", "tonal_threshold", 0.38),
        ("key_plate_gamma", "gamma", 0.88),
        ("key_plate_chroma_protection", "chroma_protection", 0.035),
        ("key_plate_min_density", "min_density", 0.0),
        ("key_plate_max_density", "max_density", 1.0),
    ):
        value = params.get(param, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{param} deve ser numérico.")
        values[field_name] = float(value)
    return KeyPlateConfig(
        enabled=enabled,
        mode=cast(KeyPlateMode, mode),
        merge_compatible_dark=merge,
        **values,
    )


def sim_process_config_from_params(params: dict[str, Any]) -> SimProcessConfig:
    """``params["sim_process"]``: ausente/False = desligado, True = defaults, objeto = campos."""
    value = params.get("sim_process")
    if isinstance(value, SimProcessConfig):
        return value
    return SimProcessConfig.from_dict(value)


def ink_library_from_params(params: dict[str, Any]) -> InkLibrarySnapshot:
    value = params.get("ink_library_snapshot")
    if value is None:
        return default_ink_library()
    if isinstance(value, InkLibrarySnapshot):
        return value
    if not isinstance(value, dict):
        raise TypeError("ink_library_snapshot deve ser um objeto JSON.")
    return InkLibrarySnapshot.from_dict(value)


def physical_measurement_from_params(
    params: dict[str, Any],
) -> PhysicalMeasurementProfile:
    value = params.get("physical_measurement")
    if value is None:
        return PhysicalMeasurementProfile()
    if isinstance(value, PhysicalMeasurementProfile):
        return value
    if not isinstance(value, dict):
        raise TypeError("physical_measurement deve ser um objeto JSON.")
    return PhysicalMeasurementProfile.from_dict(value)


def _plate_to_channel_info(
    plate: ChannelPlate, result: SeparationResult
) -> ChannelInfo:
    channel = ChannelInfo.create(
        name=plate.label,
        color_rgb=plate.color_rgb,
        mask=plate.mask,
        channel_id=plate.id,
        key=plate.key,
        export_name=plate.export_name,
        role=plate.role,
        engine_version=result.manifest.engine_version,
        manifest_version=result.manifest.manifest_version,
        profile_hash=result.manifest.profile_hash,
    )
    height, width = plate.mask.shape
    layer = np.zeros((height, width, 4), dtype=np.uint8)
    layer[..., :3] = plate.color_rgb
    layer[..., 3] = (plate.mask * 255).astype(np.uint8)
    channel.set_layer_image(Image.fromarray(layer))
    return channel


def result_to_channel_infos(result: SeparationResult) -> list[ChannelInfo]:
    """Converte chapas imutáveis nos canais editáveis usados pela UI."""
    return [_plate_to_channel_info(plate, result) for plate in result.plates]


class ColorEngineFAV8PlusAdapter:
    """Adapta o contrato FAV8+ para os modelos mutáveis da interface."""

    def is_available(self) -> bool:
        return fav8_plus_engine_available()

    def process(
        self,
        image: Image.Image,
        params: dict[str, Any],
    ) -> tuple[list[ChannelInfo], Image.Image, str]:
        result = self.process_result(image, params)
        channels = result_to_channel_infos(result)
        return channels, result.preview, result.report

    def process_result(
        self,
        image: Image.Image,
        params: dict[str, Any],
    ) -> SeparationResult:
        """Retorna o contrato completo, incluindo DNA e proveniência."""
        if not self.is_available():
            raise FileNotFoundError(fav8_plus_missing_message())

        mode = params.get("mode", "auto")
        if not isinstance(mode, str):
            raise TypeError("mode deve ser uma string.")
        dark_fabric = bool(params.get("dark_fabric", True))
        return Fav8Engine(
            Fav8Config(
                mode=cast(Fav8Mode, mode),
                dark_fabric=dark_fabric,
                ink_library=ink_library_from_params(params),
                key_plate=key_plate_config_from_params(params),
                joint_cleanup=joint_cleanup_config_from_params(params),
                physical_measurement=physical_measurement_from_params(params),
                sim_process=sim_process_config_from_params(params),
            )
        ).separate(image)
