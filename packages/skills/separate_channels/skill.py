from __future__ import annotations

import logging
from typing import Any, cast

from PIL import Image

from packages.core.models.skill_context import SkillContext
from packages.core.models.skill_metadata import SkillStatus
from packages.core.models.skill_result import SkillResult
from packages.skills.base import BaseSkill
from packages.skills.fav8_plus.adapters import (
    ink_library_from_params,
    joint_cleanup_config_from_params,
    key_plate_config_from_params,
    physical_measurement_from_params,
    result_to_channel_infos,
    sim_process_config_from_params,
)
from packages.skills.fav8_plus.engine import Fav8Engine
from packages.skills.fav8_plus.loader import fav8_plus_engine_available
from packages.skills.fav8_plus.models import Fav8Config, Fav8Mode
from packages.skills.separate_channels.params_schema import PARAMS_SCHEMA

logger = logging.getLogger(__name__)


def _resolve_pil_image(context: SkillContext) -> Image.Image | None:
    pil_image: Image.Image | None = context.metadata.get("pil_image")
    if pil_image is not None:
        return pil_image
    image_data = context.metadata.get("image_array")
    if image_data is None:
        return None
    return Image.fromarray(image_data.astype("uint8"))


class SeparateChannelsSkill(BaseSkill):
    skill_id = "separate_channels"
    display_name = "Separar Canais FAV8+"
    category = "separation"
    description = "Separar arte em canais de cor com o motor FAV8+."
    input_types = ["image"]
    output_types = ["channels", "preview"]
    params_schema = PARAMS_SCHEMA
    preconditions = ["Imagem ativa carregada"]
    can_preview = True
    can_undo = True
    status = SkillStatus.IMPLEMENTED if fav8_plus_engine_available() else SkillStatus.PARTIAL

    def execute(self, context: SkillContext, params: dict[str, Any]) -> SkillResult:
        engine = params.get("engine", "fav8_plus")
        if engine != "fav8_plus":
            return SkillResult(
                ok=False,
                messages=[
                    f"Motor não suportado: {engine!r}. "
                    "Este produto executa exclusivamente o motor FAV8+."
                ],
            )

        pil_image = _resolve_pil_image(context)
        if pil_image is None:
            return SkillResult(
                ok=False,
                messages=["Nenhuma imagem ativa. Abra uma imagem antes de separar."],
            )

        logger.info("Separação FAV8+: mode=%s", params.get("mode", "auto"))
        try:
            mode = params.get("mode", "auto")
            if not isinstance(mode, str):
                raise TypeError("mode deve ser uma string.")
            dark_fabric = params.get("dark_fabric", True)
            if not isinstance(dark_fabric, bool):
                raise TypeError("dark_fabric deve ser booleano.")
            result = Fav8Engine(
                Fav8Config(
                    mode=cast(Fav8Mode, mode),
                    dark_fabric=dark_fabric,
                    ink_library=ink_library_from_params(params),
                    key_plate=key_plate_config_from_params(params),
                    joint_cleanup=joint_cleanup_config_from_params(params),
                    physical_measurement=physical_measurement_from_params(params),
                    sim_process=sim_process_config_from_params(params),
                )
            ).separate(pil_image)
            channels = result_to_channel_infos(result)
            return SkillResult(
                ok=True,
                messages=[f"Separação FAV8+ concluída com {len(channels)} canal(is)."],
                artifacts={
                    "channels": channels,
                    "channel_plates": result.plates,
                    "result_image": result.preview,
                    "channel_count": len(channels),
                    "separation_engine": "fav8_plus",
                    "separation_manifest": result.manifest,
                    "separation_manifest_json": result.manifest.to_dict(),
                    "separation_diagnostics": result.diagnostics,
                    "separation_diagnostics_json": result.diagnostics.to_dict(),
                    "artwork_dna": result.diagnostics.artwork_dna,
                    "archetype_resolution": result.diagnostics.archetype_resolution,
                    "key_plate_report": result.diagnostics.key_plate,
                    "fav8_plus_report": result.report,
                },
            )
        except Exception as exc:
            logger.exception("Erro na separação FAV8+")
            return SkillResult(ok=False, messages=[f"Erro na separação FAV8+: {exc}"])
