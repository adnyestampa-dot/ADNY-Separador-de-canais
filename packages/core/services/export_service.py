from __future__ import annotations



import logging
import re

from collections.abc import Callable, Mapping
from pathlib import Path



from PIL import Image



from packages.core.models.channel_info import ChannelInfo
from packages.core.services.channel_ops import clone_channel
from packages.image.channel_adjust import ChannelAdjustments

from packages.image.io import save_image

from packages.image.psd_spot_export import export_spot_psd
from packages.image.textile import compose_with_ground
from packages.prepress.models import PrepressConfig
from packages.prepress.operations import PrepressPlate
from packages.prepress.pdf_export import (
    export_films_pdf,
    manifest_path_for,
    write_manifest_atomic,
)
from packages.prepress.pipeline import prepare_plates_with_diagnostics
from packages.skills.fav8_plus.models import PhysicalMeasurementProfile



logger = logging.getLogger(__name__)


def edited_visible_channels(channels: list[ChannelInfo]) -> list[ChannelInfo]:
    """Snapshot exportável sem mutar canais vivos."""
    output: list[ChannelInfo] = []
    used_names: set[str] = set()
    for channel in channels:
        if not channel.visible or channel.mask is None:
            continue
        exported = clone_channel(channel)
        opacity = max(0.0, min(1.0, float(channel.opacity)))
        exported.adjustments = ChannelAdjustments()
        exported.set_mask(channel.mask.astype("float32", copy=True) * opacity)
        exported.opacity = 1.0
        base = channel.export_name or channel.name or channel.id
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-") or "channel"
        candidate = safe
        suffix = 2
        while candidate.casefold() in used_names:
            candidate = f"{safe}_{suffix}"
            suffix += 1
        used_names.add(candidate.casefold())
        exported.name = candidate
        exported.export_name = candidate
        output.append(exported)
    return output





class ExportService:

    """Handles PNG and PSD export operations."""

    def __init__(self) -> None:
        self.last_prepress_diagnostics: dict[str, object] | None = None

    def compose_edited_visible(
        self,
        channels: list[ChannelInfo],
        shape: tuple[int, int],
        ground_rgb: tuple[int, int, int] = (20, 20, 20),
    ) -> Image.Image:
        snapshot = edited_visible_channels(channels)
        return compose_with_ground(snapshot, shape, ground_rgb)



    def export_png(

        self,

        image: Image.Image,

        path: str | Path,

        dpi: tuple[float, float] = (300.0, 300.0),

    ) -> list[str]:

        save_image(image, path, dpi=dpi)

        return [f"Exportado: {path}"]



    def export_channels_as_pngs(

        self,

        channels: list[ChannelInfo],

        output_dir: str | Path,

        dpi: tuple[float, float] = (300.0, 300.0),

    ) -> list[str]:

        output_dir = Path(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)

        messages: list[str] = []

        for ch in edited_visible_channels(channels):

            if ch.layer_image is None:

                continue

            safe_name = ch.export_name or ch.name

            out_path = output_dir / f"{safe_name}.png"

            save_image(ch.layer_image, out_path, dpi=dpi)

            messages.append(f"Canal exportado: {out_path}")

            logger.info("Canal exportado: %s", out_path)

        return messages



    def export_psd(

        self,

        channels: list[ChannelInfo],

        path: str | Path,

        composite: Image.Image | None = None,
        ground_rgb: tuple[int, int, int] = (20, 20, 20),
        keep_channel_names: bool = False,

    ) -> tuple[bool, list[str], list[str]]:

        """Exporta canais como PSD spot (100% solidez), nunca como camadas.

        ``keep_channel_names``: mantém o nome da chapa (ex. ``#1 Underbase``) como nome
        do canal no PSD em vez do nome sanitizado para arquivo.
        """

        path = Path(path)

        warnings: list[str] = []

        messages: list[str] = []



        export_channels = edited_visible_channels(channels)
        if keep_channel_names:
            visible = [ch for ch in channels if ch.visible and ch.mask is not None]
            for exported, original in zip(export_channels, visible):
                exported.name = original.export_name or original.name or exported.name
                exported.export_name = exported.name
        if not export_channels:

            return False, ["Nenhum canal visível para exportar."], warnings



        try:

            first_mask = export_channels[0].mask
            assert first_mask is not None
            edited_composite = compose_with_ground(
                export_channels, first_mask.shape[:2], ground_rgb
            )
            export_spot_psd(export_channels, path, composite=edited_composite)

            spot_count = len(export_channels)

            messages.append(

                f"PSD exportado com {spot_count} canal(is) spot (100%): {path}"

            )

            logger.info("PSD spot exportado: %s", path)

            return True, messages, warnings

        except Exception as exc:

            logger.exception("Falha na exportação PSD spot")

            warnings.append(

                f"Fallback: exportando canais como PNG na mesma pasta. Erro PSD: {exc}"

            )

            out_dir = path.parent / path.stem

            msgs = self.export_channels_as_pngs(export_channels, out_dir)

            messages.extend(msgs)

            return False, messages, warnings

    def export_films_pdf(
        self,
        channels: list[ChannelInfo],
        path: str | Path,
        config: PrepressConfig | None = None,
        *,
        alpha=None,
        metadata: Mapping[str, object] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[bool, list[str], list[str]]:
        """Exporta snapshots das placas como filmes PDF sem alterar canais vivos."""
        settings = config or PrepressConfig()
        snapshot = edited_visible_channels(channels)
        if not snapshot:
            return False, ["Nenhum canal visível para exportar."], []
        plates = tuple(
            PrepressPlate(
                key=channel.key or channel.id,
                label=channel.name,
                export_name=channel.export_name or channel.name,
                color_rgb=channel.color_rgb,
                role=channel.role,
                mask=channel.mask,
            )
            for channel in snapshot
            if channel.mask is not None
        )
        try:
            if cancelled is not None and cancelled():
                raise RuntimeError("Exportação PDF cancelada.")
            result = prepare_plates_with_diagnostics(
                plates,
                settings,
                dpi=settings.film.dpi,
                alpha=alpha,
            )
            prepared = result.plates
            self.last_prepress_diagnostics = result.diagnostics
            provenance = dict(metadata or {})
            physical_value = provenance.get("physical_measurement")
            if physical_value is None:
                physical_measurement = PhysicalMeasurementProfile()
            elif isinstance(physical_value, PhysicalMeasurementProfile):
                physical_measurement = physical_value
            elif isinstance(physical_value, Mapping):
                physical_measurement = PhysicalMeasurementProfile.from_dict(physical_value)
            else:
                raise TypeError("physical_measurement do manifest deve ser um objeto.")
            effective_angles = result.diagnostics.get("angles", [])
            manifest = {
                "manifest_version": 1,
                "classification": "digital_unmeasured",
                "engine": provenance.get("engine")
                or provenance.get("separation_engine")
                or "unknown",
                "engine_version": provenance.get("engine_version"),
                "engine_hash": provenance.get("engine_hash"),
                "profile_hash": provenance.get("profile_hash"),
                "ink_library_hash": provenance.get("ink_library_hash"),
                "physical_measurement": physical_measurement.to_dict(),
                "artwork_dna": provenance.get("artwork_dna", {}),
                "archetype_resolution": provenance.get(
                    "archetype_resolution", {}
                ),
                "dpi": settings.film.dpi,
                "order": [plate.key for plate in prepared],
                "roles": [
                    {
                        "key": plate.key,
                        "export_name": plate.export_name,
                        "role": plate.role,
                    }
                    for plate in prepared
                ],
                "effective_angles": effective_angles,
                "diagnostics": result.diagnostics,
                "separation_diagnostics": provenance.get("diagnostics", {}),
                "prepress_config": settings.to_dict(),
            }
            output = export_films_pdf(
                prepared, path, settings.film, cancelled=cancelled
            )
            if cancelled is not None and cancelled():
                output.unlink(missing_ok=True)
                raise RuntimeError("Exportação PDF cancelada.")
            manifest_path = write_manifest_atomic(output, manifest)
            key_plate = next((plate for plate in prepared if plate.role == "key"), None)
            key_angle = (
                f" | ângulo key="
                f"{settings.screening.angle_for(key_plate.key, key_plate.role):g}°"
                if key_plate is not None
                else ""
            )
            message = (
                f"PDF de filmes exportado com {len(prepared)} placa(s), "
                f"1:1 a {settings.film.dpi:g} DPI{key_angle}: {output} "
                f"(manifest: {manifest_path.name})"
            )
            logger.info(message)
            collisions = result.diagnostics.get("angle_collisions", [])
            warnings = (
                [f"Colisões de ângulo detectadas: {collisions}"] if collisions else []
            )
            return True, [message], warnings
        except Exception as exc:
            if cancelled is not None and cancelled():
                Path(path).unlink(missing_ok=True)
                manifest_path_for(path).unlink(missing_ok=True)
            logger.exception("Falha na exportação PDF de filmes")
            return False, [], [f"Falha na exportação PDF de filmes: {exc}"]


