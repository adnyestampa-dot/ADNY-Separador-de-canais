"""Motor FAV8+ autocontido: seleção Smart, separação FAV5 e tune Loop v2."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image
from scipy.ndimage import minimum_filter
from skimage.color import deltaE_cie76, deltaE_ciede2000, rgb2lab
from skimage.filters import gaussian

from packages.prepress.operations import joint_cleanup_masks
from packages.skills.fav8_plus.models import (
    ArchetypeResolution,
    ArtworkDNA,
    ChannelPlate,
    Fav8Config,
    ImageInput,
    KeyPlateReport,
    ManifestEntry,
    SeparationDiagnostics,
    SeparationManifest,
    SeparationResult,
    ResolvedFav8Mode,
    SimProcessConfig,
    VALID_RESOLVED_MODES,
)
from packages.skills.fav8_plus.tune import load_tune_profile

ENGINE_NAME = "ADNY Separador"
ENGINE_RELEASE = "BETA 0.01"
ENGINE_VERSION = f"{ENGINE_NAME} {ENGINE_RELEASE}"
MANIFEST_VERSION = 3
PROFILE_SCHEMA_VERSION = 1
PRINT_ORDER = (
    "base_white", "black", "dark_blue", "brown_dark", "dark_green", "purple",
    "blue", "green", "red", "brown_light", "skin_shadow", "skin_mid",
    "gold_yellow", "orange", "light_green", "light_blue", "beige", "pink",
    "skin_light", "turquoise", "gray", "highlight_white",
)
_SIM_COVERAGE_THRESHOLD = 0.08


@dataclass(frozen=True, slots=True)
class _Channel:
    key: str
    label: str
    export_name: str
    rgb: tuple[int, int, int]
    lab_reference: tuple[float, float, float]
    id: str = ""
    role: str = "chromatic"
    gain: float = 1.0
    gamma: float = 1.0
    floor: float = 0.06
    ceiling: float = 1.0
    softness: float = 0.7
    hue_width: float = 42.0
    neighbors: tuple[str, ...] = ()
    special: bool = False

    @property
    def lab(self) -> np.ndarray:
        return np.asarray(self.lab_reference, dtype=np.float32)

    @property
    def hue(self) -> float:
        lab = self.lab
        value = math.degrees(math.atan2(float(lab[2]), float(lab[1])))
        return value + 360.0 if value < 0 else value

_MODE_CHANNELS: Mapping[str, tuple[str, ...]] = {
    "default": ("red", "orange", "gold_yellow", "blue", "green", "turquoise",
                "purple", "brown_light", "brown_dark"),
    "oceano": ("blue", "light_blue", "dark_blue", "turquoise", "green", "purple", "pink"),
    "fogo": ("red", "orange", "gold_yellow", "brown_light", "brown_dark"),
    "natureza": ("green", "light_green", "dark_green", "gold_yellow", "brown_light",
                 "brown_dark", "turquoise", "blue"),
    "realismo": ("red", "orange", "gold_yellow", "blue", "green", "turquoise", "purple",
                 "pink", "brown_light", "brown_dark", "skin_light", "skin_mid",
                 "skin_shadow", "beige"),
    "quadrinhos": ("red", "orange", "gold_yellow", "blue", "green", "turquoise",
                   "purple", "pink", "light_blue", "dark_blue", "light_green", "beige"),
}
_MODE_LIMITS = {
    "default": (4, 9), "oceano": (4, 8), "fogo": (3, 7),
    "natureza": (4, 9), "realismo": (5, 10), "quadrinhos": (4, 8),
}


@dataclass(frozen=True, slots=True)
class _EngineSettings:
    distance_metric: str = "hybrid"
    idw_power: float = 2.0
    weight_floor: float = 0.055
    neighbor_strength: float = 0.48
    hue_gate_strength: float = 0.55
    chromatic_renorm_strength: float = 0.65
    chromatic_total_gain: float = 1.0
    max_total_ink: float = 2.75
    edge_preserve: float = 0.58
    underbase_gamma: float = 1.35
    underbase_gain: float = 0.92
    underbase_min_l: float = 0.18
    underbase_choke_px: int = 1
    underbase_softness: float = 0.45
    underbase_chroma_boost: float = 0.45
    highlight_l_min: float = 88.0
    highlight_chroma_max: float = 12.0
    highlight_gamma: float = 1.75
    highlight_gain: float = 0.85
    black_l_max: float = 38.0
    black_gamma: float = 0.88
    black_chroma_subtract: float = 0.035
    gray_chroma_max: float = 18.0
    gray_l_mid: float = 50.0
    gray_gain: float = 0.88
    gray_softness: float = 1.05
    recede_black_factor: float = 0.35
    recede_highlight_factor: float = 0.52


@dataclass(frozen=True, slots=True)
class _Analysis:
    families: tuple[tuple[str, float], ...]
    tonal: tuple[tuple[str, float], ...]
    contrast: float
    chroma_mean: float
    has_highlight: bool
    has_deep_black: bool
    has_colored_dark: bool
    visible_fraction: float
    cluster_labs: tuple[tuple[np.ndarray, float, str], ...]
    notes: tuple[str, ...]


def _family(lab: np.ndarray) -> str:
    lightness, a, b = (float(v) for v in lab)
    chroma = math.hypot(a, b)
    hue = math.degrees(math.atan2(b, a)) % 360.0
    if chroma < 8:
        return "white_neutral" if lightness > 82 else (
            "black_neutral" if lightness < 24 else "gray_neutral"
        )
    if 20 <= hue <= 72 and 20 <= lightness <= 82 and chroma <= 55:
        return "skin_or_beige" if lightness >= 48 else "brown"
    ranges = (
        (18, "red"), (45, "orange"), (78, "yellow"), (165, "green"),
        (205, "cyan"), (265, "blue"), (318, "purple"), (345, "pink"),
    )
    for edge, name in ranges:
        if hue < edge:
            return name
    return "red"


def _simple_kmeans(data: np.ndarray, count: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7)
    count = max(1, min(count, len(data)))
    centers = data[rng.choice(len(data), size=count, replace=False)].astype(np.float32)
    labels = np.zeros(len(data), dtype=np.int32)
    for _ in range(24):
        new_labels = np.argmin(
            np.sum((data[:, None, :] - centers[None, :, :]) ** 2, axis=2), axis=1
        ).astype(np.int32)
        if np.array_equal(labels, new_labels):
            break
        labels = new_labels
        for index in range(count):
            selected = labels == index
            if np.any(selected):
                centers[index] = data[selected].mean(axis=0)
    return centers, labels


class Fav8Engine:
    """API pública única do FAV8+: ``Fav8Engine(config).separate(input)``."""

    def __init__(self, config: Fav8Config | None = None):
        self.config = config or Fav8Config()
        self._profile = self._load_profile(self.config.tune_profile)
        self._settings = self._build_settings(self._profile)
        self._palette = self._build_palette(self._profile, self.config.ink_library)
        self._palette_index = {channel.key: channel for channel in self._palette}
        preferred = [key for key in PRINT_ORDER if key in self._palette_index]
        preferred.extend(key for key in self._palette_index if key not in preferred)
        self._print_order = tuple(preferred)
        self._special_keys = frozenset(
            channel.key for channel in self._palette if channel.role != "chromatic"
        )
        if self.config.sim_process.enabled:
            self._palette = self._build_sim_palette(self.config.sim_process)
            self._palette_index = {channel.key: channel for channel in self._palette}
            self._print_order = tuple(channel.key for channel in self._palette)
            self._special_keys = frozenset(
                channel.key for channel in self._palette if channel.role != "chromatic"
            )

    @staticmethod
    def _build_sim_palette(config: SimProcessConfig) -> tuple[_Channel, ...]:
        output = []
        for key, label, export_name, rgb, role in config.palette:
            lab = rgb2lab(np.asarray(rgb, dtype=np.float64).reshape(1, 1, 3) / 255.0)[0, 0]
            output.append(
                _Channel(
                    key=key,
                    label=label,
                    export_name=export_name,
                    rgb=rgb,
                    lab_reference=tuple(float(v) for v in lab),
                    id=f"ss4:{key}",
                    role=role,
                    special=role != "chromatic",
                )
            )
        return tuple(output)

    @staticmethod
    def _load_profile(path: Path | None) -> dict[str, Any]:
        return load_tune_profile(path)

    @staticmethod
    def _build_settings(profile: Mapping[str, Any]) -> _EngineSettings:
        overrides = profile.get("engine", {})
        if not isinstance(overrides, Mapping):
            raise ValueError("profile.engine deve ser um objeto.")
        valid = {item.name for item in fields(_EngineSettings)}
        unknown = set(overrides) - valid
        if unknown:
            raise ValueError(f"Overrides de engine desconhecidos: {sorted(unknown)}")
        return replace(_EngineSettings(), **dict(overrides))

    @staticmethod
    def _build_palette(profile: Mapping[str, Any], ink_library: Any) -> tuple[_Channel, ...]:
        overrides = profile.get("channels", {})
        if not isinstance(overrides, Mapping):
            raise ValueError("profile.channels deve ser um objeto.")
        library_keys = {ink.key for ink in ink_library.inks}
        unknown_channels = set(overrides) - library_keys
        if unknown_channels:
            raise ValueError(f"Overrides de canais desconhecidos: {sorted(unknown_channels)}")
        valid = {
            "gain", "gamma", "floor", "ceiling", "softness", "hue_width", "neighbors"
        }
        output = []
        for ink in ink_library.inks:
            engine_metadata = ink.metadados.get("engine", {})
            if not isinstance(engine_metadata, Mapping):
                raise ValueError(f"metadados.engine de {ink.id!r} deve ser um objeto.")
            unknown_metadata = set(engine_metadata) - valid
            if unknown_metadata:
                raise ValueError(
                    f"Ajustes de engine desconhecidos em {ink.id!r}: {sorted(unknown_metadata)}"
                )
            export_name = ink.metadados.get("export_name", ink.key.upper())
            if not isinstance(export_name, str) or not export_name:
                raise ValueError(f"export_name de {ink.id!r} deve ser uma string.")
            base_values = dict(engine_metadata)
            if "neighbors" in base_values:
                base_values["neighbors"] = tuple(base_values["neighbors"])
            channel = _Channel(
                key=ink.key,
                label=ink.nome,
                export_name=export_name,
                rgb=ink.display_rgb,
                id=ink.id,
                role=ink.role,
                lab_reference=ink.lab_reference,
                special=ink.role != "chromatic",
                **base_values,
            )
            values = overrides.get(channel.key, {})
            if not isinstance(values, Mapping):
                raise ValueError(f"Override do canal {channel.key!r} deve ser um objeto.")
            unknown = set(values) - valid
            if unknown:
                raise ValueError(
                    f"Overrides desconhecidos em {channel.key!r}: {sorted(unknown)}"
                )
            normalized = dict(values)
            if "neighbors" in normalized:
                normalized["neighbors"] = tuple(normalized["neighbors"])
            output.append(replace(channel, **normalized))
        return tuple(output)

    def separate(self, image_input: ImageInput) -> SeparationResult:
        rgb, alpha = self._read_input(image_input)
        analysis = self._analyze(rgb, alpha)
        artwork_dna = self._artwork_dna(analysis)
        archetype = self._resolve_archetype(artwork_dna)
        sim_enabled = self.config.sim_process.enabled
        notes = analysis.notes
        garment = None
        if sim_enabled:
            channels, garment, sim_notes = self._separate_sim_process(rgb, alpha)
            active, pruned = list(self._print_order), []
            notes = (*notes, *sim_notes)
            key_plate_report = KeyPlateReport(
                enabled=False,
                mode=self.config.key_plate.mode,
                effective_tonal_threshold=self.config.key_plate.tonal_threshold,
            )
        else:
            active, pruned = self._select_channels(analysis, archetype.resolved_mode)
            channels = self._separate_core(rgb, alpha, active)
            channels = self._calibrate(channels, alpha)
            channels, key_plate_report = self._apply_key_plate(
                channels, rgb, alpha, analysis
            )
        channel_keys = tuple(channels)
        cleaned_masks, cleanup_report = joint_cleanup_masks(
            tuple(channels[key] for key in channel_keys),
            self.config.joint_cleanup,
            alpha=alpha,
            dpi=self.config.joint_cleanup.dpi,
            lpi=self.config.joint_cleanup.lpi,
            copy=False,
        )
        channels = dict(zip(channel_keys, cleaned_masks, strict=True))
        channels = {key: channels[key] for key in self._print_order if key in channels}
        plates = tuple(
            ChannelPlate(
                id=self._palette_index[key].id,
                key=key,
                label=self._palette_index[key].label,
                export_name=self._palette_index[key].export_name,
                role=self._palette_index[key].role,
                color_rgb=self._palette_index[key].rgb,
                mask=mask,
            )
            for key, mask in channels.items()
        )
        if sim_enabled and self.config.sim_process.preview == "additive":
            assert garment is not None
            preview = self._compose_sim_preview(
                plates,
                garment,
                self.config.sim_process.gray_residual_weight,
                dict(self.config.sim_process.preview_ink_rgb),
            )
        else:
            preview = self._compose_preview(plates)
        manifest = SeparationManifest(
            manifest_version=MANIFEST_VERSION,
            engine="fav8_plus",
            engine_version=ENGINE_VERSION,
            profile_schema_version=int(self._profile["schema_version"]),
            profile_version=str(self._profile["profile_version"]),
            profile_hash=str(self._profile["profile_hash"]),
            ink_library_schema_version=self.config.ink_library.schema_version,
            ink_library_version=self.config.ink_library.version,
            ink_library_hash=self.config.ink_library.hash,
            ink_library_snapshot=self.config.ink_library.to_dict(),
            mode=archetype.resolved_mode,
            dark_fabric=self.config.dark_fabric,
            width=rgb.shape[1],
            height=rgb.shape[0],
            channels=tuple(
                ManifestEntry(
                    id=plate.id,
                    key=plate.key,
                    label=plate.label,
                    export_name=plate.export_name,
                    role=plate.role,
                    color_rgb=plate.color_rgb,
                    print_index=index,
                    is_special=plate.key in self._special_keys,
                )
                for index, plate in enumerate(plates)
            ),
            tune_source=str(self._profile.get("source", "unknown")),
            artwork_dna=artwork_dna,
            archetype_resolution=archetype,
            joint_cleanup=cleanup_report,
            key_plate=key_plate_report,
            physical_measurement=self.config.physical_measurement,
        )
        diagnostics = SeparationDiagnostics(
            active_channels=tuple(active),
            pruned_channels=tuple(pruned),
            dominant_families=analysis.families,
            tonal_distribution=analysis.tonal,
            contrast_index=analysis.contrast,
            chroma_mean=analysis.chroma_mean,
            notes=notes,
            artwork_dna=artwork_dna,
            archetype_resolution=archetype,
            joint_cleanup=cleanup_report,
            key_plate=key_plate_report,
            profile=self._profile,
            ink_library_schema_version=self.config.ink_library.schema_version,
            ink_library_version=self.config.ink_library.version,
            ink_library_hash=self.config.ink_library.hash,
            ink_library_snapshot=self.config.ink_library.to_dict(),
        )
        report = self._report(plates, diagnostics)
        return SeparationResult(plates, preview, manifest, diagnostics, report)

    @staticmethod
    def _read_input(image_input: ImageInput) -> tuple[np.ndarray, np.ndarray]:
        if isinstance(image_input, (str, Path)):
            with Image.open(image_input) as opened:
                array = np.asarray(opened.convert("RGBA"), dtype=np.float32) / 255.0
        elif isinstance(image_input, Image.Image):
            array = np.asarray(image_input.convert("RGBA"), dtype=np.float32) / 255.0
        elif isinstance(image_input, np.ndarray):
            array = np.asarray(image_input)
            if array.ndim != 3 or array.shape[-1] not in (3, 4):
                raise ValueError("Imagem numpy deve ter formato H×W×3 ou H×W×4.")
            if not np.issubdtype(array.dtype, np.number):
                raise TypeError("Imagem numpy deve conter valores numéricos.")
            array = array.astype(np.float32)
            if not np.isfinite(array).all():
                raise ValueError("Imagem contém valores não finitos.")
            if array.size and float(array.max()) > 1.0:
                array /= 255.0
            if array.shape[-1] == 3:
                array = np.dstack(
                    (array, np.ones(array.shape[:2], dtype=np.float32))
                )
            array = np.clip(array, 0.0, 1.0)
        else:
            raise TypeError("Entrada deve ser PIL.Image, caminho ou ndarray RGB/RGBA.")
        if array.shape[0] == 0 or array.shape[1] == 0:
            raise ValueError("Imagem vazia.")
        return array[..., :3].astype(np.float32), array[..., 3].astype(np.float32)

    def _analyze(self, rgb: np.ndarray, alpha: np.ndarray) -> _Analysis:
        height, width = alpha.shape
        if max(height, width) > self.config.analysis_max_size:
            scale = self.config.analysis_max_size / max(height, width)
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            rgb_small = np.asarray(
                Image.fromarray((rgb * 255).astype(np.uint8)).resize(
                    size, Image.Resampling.LANCZOS
                ),
                dtype=np.float32,
            ) / 255.0
            alpha_small = np.asarray(
                Image.fromarray((alpha * 255).astype(np.uint8)).resize(
                    size, Image.Resampling.LANCZOS
                ),
                dtype=np.float32,
            ) / 255.0
        else:
            rgb_small, alpha_small = rgb, alpha
        valid = alpha_small > 0.03
        if not np.any(valid):
            raise ValueError("Imagem sem área visível de alpha.")
        labs = rgb2lab(rgb_small)[valid].astype(np.float32)
        if len(labs) > 70000:
            rng = np.random.default_rng(123)
            sample = labs[rng.choice(len(labs), size=70000, replace=False)]
        else:
            sample = labs
        lightness = labs[:, 0]
        chroma = np.hypot(labs[:, 1], labs[:, 2])
        l10, _, l90 = (float(v) for v in np.percentile(lightness, (10, 50, 90)))
        centers, labels = _simple_kmeans(sample, min(max(4, self.config.max_clusters), 16))
        family_totals: dict[str, float] = {}
        clusters: list[tuple[np.ndarray, float, str]] = []
        for index, center in enumerate(centers):
            selected = labels == index
            if not np.any(selected):
                continue
            coverage = float(selected.mean())
            family = _family(center)
            family_totals[family] = family_totals.get(family, 0.0) + coverage
            clusters.append((center.copy(), coverage, family))
        clusters.sort(key=lambda item: item[1], reverse=True)
        families = tuple(sorted(family_totals.items(), key=lambda item: item[1], reverse=True))
        tonal = (
            ("shadow", float(np.mean(lightness < 34.0))),
            ("midtone", float(np.mean((lightness >= 34.0) & (lightness < 72.0)))),
            ("highlight", float(np.mean(lightness >= 72.0))),
        )
        has_highlight = dict(tonal)["highlight"] > 0.06
        has_deep_black = dict(tonal)["shadow"] > 0.12 and l10 < 24.0
        colored_dark = any(
            float(center[0]) < 34 and math.hypot(float(center[1]), float(center[2])) > 14
            and coverage > 0.04
            for center, coverage, _ in clusters
        )
        notes = []
        if families:
            notes.append(f"Família dominante: {families[0][0]}")
        if colored_dark:
            notes.append("Escuros coloridos detectados")
        if has_highlight:
            notes.append("Altas luzes detectadas")
        return _Analysis(
            families=families,
            tonal=tonal,
            contrast=float(np.clip((l90 - l10) / 100.0, 0.0, 1.0)),
            chroma_mean=float(chroma.mean()),
            has_highlight=has_highlight,
            has_deep_black=has_deep_black,
            has_colored_dark=colored_dark,
            visible_fraction=float(np.mean(valid)),
            cluster_labs=tuple(clusters),
            notes=tuple(notes),
        )

    @staticmethod
    def _artwork_dna(analysis: _Analysis) -> ArtworkDNA:
        return ArtworkDNA(
            dominant_families=analysis.families,
            tonal_distribution=analysis.tonal,
            contrast_index=analysis.contrast,
            chroma_mean=analysis.chroma_mean,
            visible_fraction=analysis.visible_fraction,
            has_highlight=analysis.has_highlight,
            has_deep_black=analysis.has_deep_black,
            has_colored_dark=analysis.has_colored_dark,
        )

    def _resolve_archetype(self, dna: ArtworkDNA) -> ArchetypeResolution:
        requested = self.config.mode
        if requested != "auto":
            return ArchetypeResolution(
                requested_mode=requested,
                resolved_mode=requested,
                confidence=1.0,
                reasons=(f"Modo {requested} selecionado manualmente.",),
                source="override",
            )

        families = dict(dna.dominant_families)
        ocean = (
            families.get("blue", 0.0)
            + families.get("cyan", 0.0)
            + 0.8 * families.get("purple", 0.0)
        )
        fire = (
            families.get("red", 0.0)
            + families.get("orange", 0.0)
            + families.get("yellow", 0.0)
        )
        nature = (
            families.get("green", 0.0)
            + families.get("brown", 0.0)
            + 0.35 * families.get("yellow", 0.0)
        )
        skin = families.get("skin_or_beige", 0.0)
        family_count = sum(coverage >= 0.06 for coverage in families.values())
        tonal = dict(dna.tonal_distribution)
        tonal_balance = 1.0 - max(tonal.values(), default=1.0)
        chroma = float(np.clip(dna.chroma_mean / 55.0, 0.0, 1.0))

        scores: dict[ResolvedFav8Mode, float] = {
            "default": 0.28 + 0.035 * min(family_count, 6) + 0.12 * tonal_balance,
            "oceano": 0.16 + 1.25 * ocean + 0.08 * float(dna.has_colored_dark),
            "fogo": 0.16 + 1.25 * fire + 0.10 * dna.contrast_index,
            "natureza": 0.16 + 1.2 * nature + 0.06 * tonal_balance,
            "realismo": (
                0.18
                + 1.35 * skin
                + 0.18 * tonal_balance
                + 0.08 * float(dna.has_highlight and dna.has_deep_black)
            ),
            "quadrinhos": 0.18 + 0.34 * dna.contrast_index + 0.34 * chroma,
        }
        ranked = sorted(
            scores.items(),
            key=lambda item: (-item[1], VALID_RESOLVED_MODES.index(item[0])),
        )
        resolved, best = ranked[0]
        second = ranked[1][1]
        confidence = float(np.clip(0.5 + (best - second) / max(best, 0.25), 0.5, 0.99))
        dominant = dna.dominant_families[0][0] if dna.dominant_families else "indefinida"
        reasons = (
            f"Família dominante: {dominant}.",
            f"Contraste {dna.contrast_index:.3f} e chroma médio {dna.chroma_mean:.3f}.",
            f"Pontuação {resolved}={best:.3f}; alternativa={ranked[1][0]} ({second:.3f}).",
        )
        return ArchetypeResolution(
            requested_mode="auto",
            resolved_mode=resolved,
            confidence=confidence,
            reasons=reasons,
            source="auto",
        )

    def _select_channels(
        self,
        analysis: _Analysis,
        mode: ResolvedFav8Mode,
    ) -> tuple[list[str], list[str]]:
        candidates = [
            key for key in _MODE_CHANNELS[mode]
            if key in self._palette_index and self._palette_index[key].role == "chromatic"
        ]
        candidates.extend(
            channel.key
            for channel in self._palette
            if channel.role == "chromatic" and channel.key not in candidates
        )
        if not self.config.smart_pruning:
            selected = candidates
        else:
            family_coverage = dict(analysis.families)
            scored: list[tuple[float, str]] = []
            for key in candidates:
                channel = self._palette_index[key]
                family = _family(channel.lab)
                distances = [
                    float(deltaE_ciede2000(center[None, None], channel.lab[None, None])[0, 0])
                    * (1.0 - min(coverage, 0.35) * 0.45)
                    for center, coverage, _ in analysis.cluster_labs
                ]
                distance = min(distances, default=999.0)
                coverage = family_coverage.get(family, 0.0)
                score = 0.52 * np.clip(1.0 - distance / 55.0, 0.0, 1.0)
                score += 0.36 * np.clip(coverage * 3.4, 0.0, 1.0)
                if key in _MODE_CHANNELS[mode]:
                    score += 0.08
                scored.append((float(score), key))
            minimum, maximum = _MODE_LIMITS[mode]
            minimum = self.config.min_active_chromatic or minimum
            maximum = self.config.max_active_chromatic or maximum
            enabled = [
                (score, key) for score, key in scored
                if score >= self.config.min_channel_score
            ]
            enabled.sort(reverse=True)
            if len(enabled) < minimum:
                enabled = sorted(scored, reverse=True)[:minimum]
            selected = [key for _, key in enabled[:maximum]]
        active = (
            [key for key in self._print_order if key in self._special_keys]
            if self.config.include_specials else []
        )
        if self.config.key_plate.enabled and "black" not in active:
            active.append("black")
        active.extend(selected)
        active = [key for key in self._print_order if key in active]
        pruned = [key for key in candidates if key not in selected]
        return active, pruned

    def _separate_core(
        self, rgb: np.ndarray, alpha: np.ndarray, active_keys: list[str]
    ) -> dict[str, np.ndarray]:
        settings = self._settings
        lab = rgb2lab(np.clip(rgb, 0.0, 1.0)).astype(np.float32)
        chroma = np.hypot(lab[..., 1], lab[..., 2]).astype(np.float32)
        hue = np.degrees(np.arctan2(lab[..., 2], lab[..., 1]))
        hue = np.where(hue < 0, hue + 360.0, hue).astype(np.float32)
        output: dict[str, np.ndarray] = {}
        lightness = lab[..., 0]
        if "base_white" in active_keys:
            normalized = np.clip(
                (lightness - settings.underbase_min_l * 100.0)
                / (100.0 - settings.underbase_min_l * 100.0), 0.0, 1.0
            )
            normalized = _smoothstep(normalized)
            boost = ((1.0 - settings.underbase_chroma_boost)
                     + settings.underbase_chroma_boost * np.clip(chroma / 60.0, 0, 1))
            base = normalized * boost * alpha
            base = np.power(np.clip(base, 0, 1), settings.underbase_gamma)
            base *= settings.underbase_gain
            if settings.underbase_choke_px > 0:
                eroded = minimum_filter(base, size=settings.underbase_choke_px * 2 + 1)
                base = 0.75 * eroded + 0.25 * base
            if settings.underbase_softness > 0:
                base = gaussian(base, sigma=settings.underbase_softness)
            output["base_white"] = np.clip(base, 0, 1).astype(np.float32)
        if "black" in active_keys:
            dark = np.clip(1.0 - lightness / settings.black_l_max, 0, 1)
            reduce = np.clip(1.0 - chroma * settings.black_chroma_subtract, 0, 1)
            output["black"] = np.power(
                np.clip(_smoothstep(dark) * reduce * alpha, 0, 1),
                settings.black_gamma,
            ).astype(np.float32)
        if "highlight_white" in active_keys:
            light = np.clip(
                (lightness - settings.highlight_l_min)
                / max(100.0 - settings.highlight_l_min, 1e-6), 0, 1
            )
            neutral = np.clip(
                1.0 - chroma / max(settings.highlight_chroma_max, 1e-6), 0, 1
            )
            highlight = _smoothstep(light) * _smoothstep(neutral) * alpha
            output["highlight_white"] = (
                np.power(np.clip(highlight, 0, 1), settings.highlight_gamma)
                * settings.highlight_gain
            ).astype(np.float32)
        if "gray" in active_keys:
            gate = _smoothstep(
                np.clip(1.0 - chroma / max(settings.gray_chroma_max, 1e-6), 0, 1)
            )
            bell = _smoothstep(
                np.clip(1.0 - np.abs(lightness - settings.gray_l_mid) / 50.0, 0, 1)
            )
            gray = bell * gate * settings.gray_gain * alpha
            output["gray"] = np.clip(
                gaussian(gray, sigma=settings.gray_softness), 0, 1
            ).astype(np.float32)
        chromatic = [
            self._palette_index[key]
            for key in active_keys
            if self._palette_index[key].role == "chromatic"
        ]
        if chromatic:
            output.update(self._chromatic(lab, alpha, chroma, hue, chromatic))
        sample = next(iter(output.values()))
        black = output.get("black", np.zeros_like(sample))
        highlight = output.get("highlight_white", np.zeros_like(sample))
        suppress = 1.0 - np.clip(
            black * settings.recede_black_factor
            + highlight * settings.recede_highlight_factor, 0, 1
        )
        for key in output:
            if key not in self._special_keys:
                output[key] = np.clip(output[key] * suppress, 0, 1).astype(np.float32)
        stack_keys = list(output)
        stack = np.stack([output[key] for key in stack_keys])
        total = stack.sum(axis=0)
        scale = np.where(
            total > settings.max_total_ink,
            settings.max_total_ink / np.maximum(total, 1e-8),
            1.0,
        )
        sigma = max(0.25, (1.0 - settings.edge_preserve) * 1.2)
        for index, key in enumerate(stack_keys):
            value = np.clip(stack[index] * scale, 0, 1)
            smoothed = gaussian(value, sigma=sigma)
            value = value * settings.edge_preserve + smoothed * (1 - settings.edge_preserve)
            output[key] = np.clip(value * alpha, 0, 1).astype(np.float32)
        return output

    def _apply_key_plate(
        self,
        channels: dict[str, np.ndarray],
        rgb: np.ndarray,
        alpha: np.ndarray,
        analysis: _Analysis,
    ) -> tuple[dict[str, np.ndarray], KeyPlateReport]:
        """Recalcula a chapa preta in-place lógico, sem criar uma segunda chapa."""
        config = self.config.key_plate
        if not config.enabled:
            return channels, KeyPlateReport(
                enabled=False,
                mode=config.mode,
                effective_tonal_threshold=config.tonal_threshold,
            )

        threshold = config.tonal_threshold
        if config.mode == "auto":
            # Contraste alto tolera uma key um pouco mais profunda; em artes
            # suaves a automação mantém mais detalhe de sombra.
            threshold *= 0.9 + 0.2 * analysis.contrast
        threshold = float(np.clip(threshold, 1e-6, 1.0))

        lab = rgb2lab(np.clip(rgb, 0.0, 1.0)).astype(np.float32)
        lightness = lab[..., 0] / 100.0
        chroma = np.hypot(lab[..., 1], lab[..., 2]).astype(np.float32)
        tonal = _smoothstep(np.clip((threshold - lightness) / threshold, 0, 1))
        protection = np.clip(1.0 - chroma * config.chroma_protection, 0, 1)
        key = np.power(np.clip(tonal * protection, 0, 1), config.gamma)
        positive = key > 0
        key[positive] = np.clip(
            key[positive], config.min_density, config.max_density
        )
        key = np.minimum(key * alpha, alpha).astype(np.float32)

        merged: list[str] = []
        if config.merge_compatible_dark:
            for candidate in ("dark_blue", "brown_dark", "dark_green"):
                mask = channels.get(candidate)
                if mask is None:
                    continue
                # Só incorpora a parcela que toca a região tonal da key. Isso
                # evita converter massas cromáticas escuras isoladas em preto.
                compatible = np.minimum(mask, np.clip(tonal * alpha, 0, 1))
                if np.any(compatible > 0):
                    key = np.maximum(key, compatible).astype(np.float32)
                    merged.append(candidate)

        key = np.minimum(np.clip(key, 0, config.max_density), alpha)
        output = dict(channels)
        output["black"] = key.astype(np.float32)
        return output, KeyPlateReport(
            enabled=True,
            mode=config.mode,
            effective_tonal_threshold=threshold,
            merged_channel_keys=tuple(merged),
        )

    def _chromatic(
        self,
        lab: np.ndarray,
        alpha: np.ndarray,
        chroma: np.ndarray,
        hue: np.ndarray,
        active: list[_Channel],
    ) -> dict[str, np.ndarray]:
        settings = self._settings
        raw = []
        for channel in active:
            reference = channel.lab.reshape(1, 1, 3)
            if settings.distance_metric == "cie76":
                distance = deltaE_cie76(lab, reference)
            elif settings.distance_metric == "ciede2000":
                distance = deltaE_ciede2000(lab, reference)
            elif settings.distance_metric == "hybrid":
                distance = (
                    0.4 * deltaE_cie76(lab, reference)
                    + 0.6 * deltaE_ciede2000(lab, reference)
                )
            else:
                raise ValueError(
                    f"Métrica de distância inválida: {settings.distance_metric!r}"
                )
            raw.append((1.0 / np.maximum(distance, 0.45) ** settings.idw_power).astype(np.float32))
        normalized = _normalize(np.stack(raw))
        normalized = _normalize(np.where(normalized < settings.weight_floor, 0.0, normalized))
        curved: dict[str, np.ndarray] = {}
        for index, channel in enumerate(active):
            weight = normalized[index]
            distance = np.minimum(
                np.abs(hue - channel.hue), 360.0 - np.abs(hue - channel.hue)
            )
            gate = np.exp(-0.5 * (distance / max(channel.hue_width, 1.0)) ** 2)
            strength = settings.hue_gate_strength * np.clip(chroma / 22.0, 0, 1)
            weight *= (1.0 - strength) + strength * gate
            weight = np.power(np.clip(weight, 0, 1), channel.gamma) * channel.gain
            weight = np.where(weight < channel.floor, 0.0, weight)
            weight = np.clip(weight, 0, channel.ceiling)
            if channel.softness > 0:
                weight = np.clip(gaussian(weight, sigma=channel.softness), 0, channel.ceiling)
            curved[channel.key] = weight.astype(np.float32)
        controlled: dict[str, np.ndarray] = {}
        for channel in active:
            weight = curved[channel.key]
            allowed = set(channel.neighbors) | {channel.key}
            non_neighbor = np.zeros_like(weight)
            for other in active:
                if other.key not in allowed:
                    non_neighbor = np.maximum(non_neighbor, curved[other.key])
            dominance = np.clip(non_neighbor - weight, 0, 1)
            controlled[channel.key] = np.clip(
                weight * (1.0 - dominance * settings.neighbor_strength), 0, 1
            )
        stack = np.stack([controlled[channel.key] for channel in active])
        current = stack.sum(axis=0, keepdims=True)
        target = (
            _smoothstep(np.clip(chroma / 30.0, 0, 1))[None]
            * alpha[None] * settings.chromatic_total_gain
        )
        factor = np.clip(
            np.divide(target, np.maximum(current, 1e-8), out=np.zeros_like(target),
                      where=current > 1e-8),
            0.0, 1.35,
        )
        blend = np.clip(settings.chromatic_renorm_strength, 0, 1)
        final = stack * (1.0 - blend) + stack * factor * blend
        return {
            channel.key: np.clip(final[index], 0, channel.ceiling).astype(np.float32)
            for index, channel in enumerate(active)
        }

    def _calibrate(
        self, channels: dict[str, np.ndarray], alpha: np.ndarray
    ) -> dict[str, np.ndarray]:
        calibration = self._profile.get("calibration", {})
        if not isinstance(calibration, Mapping):
            raise ValueError("profile.calibration deve ser um objeto.")
        output = dict(channels)
        for key, values in calibration.items():
            if key not in output:
                continue
            if not isinstance(values, Mapping):
                raise ValueError(f"Calibração de {key!r} deve ser um objeto.")
            invalid = set(values) - {"scale", "offset"}
            if invalid:
                raise ValueError(f"Calibrações desconhecidas em {key!r}: {sorted(invalid)}")
            # Escala/offset são definidos na densidade relativa à área visível.
            # Reaplicar alpha depois da curva impede tinta fora do recorte,
            # inclusive quando uma calibração usa offset positivo.
            relative = np.divide(
                output[key],
                alpha,
                out=np.zeros_like(output[key]),
                where=alpha > 1e-8,
            )
            calibrated = np.clip(
                relative * float(values.get("scale", 1.0))
                + float(values.get("offset", 0.0)),
                0.0,
                1.0,
            )
            output[key] = np.minimum(calibrated * alpha, alpha).astype(np.float32)
        for key, mask in output.items():
            output[key] = np.minimum(np.clip(mask, 0.0, 1.0), alpha).astype(np.float32)
        return output

    def _separate_sim_process(
        self, rgb: np.ndarray, alpha: np.ndarray
    ) -> tuple[dict[str, np.ndarray], np.ndarray, tuple[str, ...]]:
        """Simulated Process SS4: soma não-negativa de tintas fixas sobre a camiseta.

        Gray e cores são funções só da cor do pixel, então são resolvidos uma vez
        por cor única (quantizada em ``color_bits``) e reindexados; o underbase é
        calculado por pixel para não criar degraus na rampa tonal.
        """
        config = self.config.sim_process
        notes: list[str] = []
        garment = self._sim_garment(rgb, config)
        garment_l = float(rgb2lab(garment.reshape(1, 1, 3))[0, 0, 0])
        if garment_l >= 20.0:
            notes.append(
                f"Sim process: camiseta clara (L*={garment_l:.0f}); modelo aditivo assume fundo escuro."
            )

        bits = config.color_bits
        shift = 8 - bits
        level_mask = (1 << bits) - 1
        quantized = (np.rint(np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.int32)) >> shift
        codes = (quantized[..., 0] << (2 * bits)) | (quantized[..., 1] << bits) | quantized[..., 2]
        del quantized
        present = np.zeros(1 << (3 * bits), dtype=bool)
        present[codes.ravel()] = True
        unique = np.flatnonzero(present)
        lookup = np.zeros(1 << (3 * bits), dtype=np.int32)
        lookup[unique] = np.arange(len(unique), dtype=np.int32)
        inverse = lookup[codes]
        del codes, present, lookup
        levels = np.stack(
            ((unique >> (2 * bits)) & level_mask, (unique >> bits) & level_mask, unique & level_mask),
            axis=-1,
        ).astype(np.float64)
        step = float(1 << shift)
        colors = (levels * step + (step - 1.0) / 2.0) / 255.0

        values, knockout = self._sim_color_model(colors, garment, config)
        keep = 1.0 - knockout

        output: dict[str, np.ndarray] = {}
        underbase_key = next(
            (channel.key for channel in self._palette if channel.role == "underbase"), None
        )
        for channel in self._palette:
            if channel.key == underbase_key:
                value = rgb.max(axis=-1)
                ramp = np.clip(
                    (value - config.underbase_v0) / (config.underbase_v1 - config.underbase_v0),
                    0.0,
                    1.0,
                )
                plate = config.underbase_max * np.power(ramp, config.underbase_gamma)
                plate *= keep.astype(np.float32)[inverse]
                if config.underbase_choke_px > 0:
                    eroded = minimum_filter(plate, size=config.underbase_choke_px * 2 + 1)
                    plate = 0.75 * eroded + 0.25 * plate
            else:
                plate = (values[channel.key] * keep).astype(np.float32)[inverse]
            plate = np.clip(plate * alpha, 0.0, 1.0).astype(np.float32)
            if (
                channel.key != underbase_key
                and config.min_plate_coverage > 0
                and float((plate > _SIM_COVERAGE_THRESHOLD).mean()) < config.min_plate_coverage
            ):
                plate = np.zeros_like(plate)
            output[channel.key] = plate
        empty = [channel.label for channel in self._palette if not output[channel.key].any()]
        notes.append(
            f"Sim process SS4: {len(self._palette)} chapas fixas, {len(unique)} cores únicas "
            f"({bits} bits/canal)" + (f"; vazias: {', '.join(empty)}" if empty else "")
        )
        return output, garment, tuple(notes)

    @staticmethod
    def _sim_garment(rgb: np.ndarray, config: SimProcessConfig) -> np.ndarray:
        if config.garment_rgb is not None:
            return np.asarray(config.garment_rgb, dtype=np.float32) / 255.0
        height, width = rgb.shape[:2]
        border = max(1, int(round(min(height, width) * 0.02)))
        frame = np.concatenate(
            (
                rgb[:border].reshape(-1, 3),
                rgb[-border:].reshape(-1, 3),
                rgb[:, :border].reshape(-1, 3),
                rgb[:, -border:].reshape(-1, 3),
            )
        )
        return np.median(frame, axis=0).astype(np.float32)

    def _sim_color_model(
        self, colors: np.ndarray, garment: np.ndarray, config: SimProcessConfig
    ) -> tuple[dict[str, np.ndarray], np.ndarray]:
        """Densidades por cor única: Gray por regra, cores + Top White por NNLS esparso em sRGB."""
        lab = rgb2lab(colors.reshape(-1, 1, 3)).reshape(-1, 3)
        lightness = lab[:, 0]
        chroma = np.hypot(lab[:, 1], lab[:, 2])
        gains = config.gains
        lambdas = config.lambdas
        values: dict[str, np.ndarray] = {}
        residual = colors
        neutral = next((c for c in self._palette if c.role == "neutral"), None)
        if neutral is not None:
            bell = np.clip(1.0 - np.abs(lightness - config.gray_l_mid) / config.gray_width, 0, 1)
            chroma_max = np.maximum(
                config.gray_chroma_max + config.gray_chroma_slope * (lightness - 50.0), 1.0
            )
            gray = config.gray_gain * bell * _smoothstep(1.0 - chroma / chroma_max)
            gray = np.clip(gray * gains.get(neutral.key, 1.0), 0.0, 1.0)
            # O Gray sobre underbase clareia mais que a soma aditiva; o peso
            # desconta esse excesso para o resíduo não virar Top White nos médios.
            residual = np.clip(
                colors
                - gray[:, None]
                * config.gray_residual_weight
                * (np.asarray(neutral.rgb, dtype=np.float64) / 255.0),
                0.0,
                1.0,
            )
            values[neutral.key] = gray
        additive = [c for c in self._palette if c.role in {"chromatic", "highlight"}]
        basis = np.asarray([c.rgb for c in additive], dtype=np.float64).T / 255.0
        penalty = np.asarray(
            [lambdas.get(c.key, config.nnls_lambda) for c in additive], dtype=np.float64
        )
        solution = _nnls_projected(
            basis, residual, penalty, config.nnls_iters, config.nnls_solver == "fista"
        )
        for index, channel in enumerate(additive):
            density = solution[:, index] * gains.get(channel.key, 1.0)
            if channel.role == "highlight" and config.top_white_neutral_boost > 0:
                density = density + config.top_white_neutral_boost * np.clip(
                    (colors.min(axis=1) - 0.5) / 0.5, 0.0, 1.0
                )
            values[channel.key] = np.clip(density, 0.0, 1.0)
        if config.ink_hue_gates:
            hue = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360.0
            for key, (low, high, soft) in config.ink_hue_gates:
                if key in values:
                    center, half = (low + high) / 2.0, (high - low) / 2.0
                    offset = np.abs((hue - center + 180.0) % 360.0 - 180.0)
                    values[key] = values[key] * _smoothstep(
                        1.0 - np.maximum(offset - half, 0.0) / soft
                    )
        for key, density in values.items():
            values[key] = np.where(density < config.ink_floor, 0.0, density)
        if config.knockout_tolerance > 0:
            distance = np.linalg.norm(colors - garment[None, :].astype(np.float64), axis=1)
            knockout = _smoothstep(1.0 - distance / config.knockout_tolerance)
        else:
            knockout = np.zeros(len(colors), dtype=np.float64)
        return values, knockout

    @staticmethod
    def _compose_sim_preview(
        plates: tuple[ChannelPlate, ...],
        garment: np.ndarray,
        gray_weight: float = 1.0,
        ink_rgb: Mapping[str, tuple[float, float, float]] | None = None,
    ) -> Image.Image:
        """Prova aditiva coerente com o modelo: tintas somadas sobre a camiseta."""
        if not plates:
            raise ValueError("Separação não produziu canais.")
        ink_rgb = ink_rgb or {}
        height, width = plates[0].mask.shape
        ink_sum = np.zeros((height, width, 3), dtype=np.float32)
        coverage = np.zeros((height, width), dtype=np.float32)
        for plate in plates:
            coverage = np.maximum(coverage, plate.mask)
            if plate.key in ink_rgb:
                ink = np.asarray(ink_rgb[plate.key], dtype=np.float32) / 255.0
                ink_sum += plate.mask[..., None] * ink
                continue
            if plate.role == "underbase":
                continue
            ink = np.asarray(plate.color_rgb, dtype=np.float32) / 255.0
            if plate.role == "neutral":
                ink = ink * np.float32(gray_weight)
            ink_sum += plate.mask[..., None] * ink
        composite = garment.astype(np.float32) * (1.0 - coverage[..., None]) + ink_sum
        return Image.fromarray((np.clip(composite, 0, 1) * 255).astype(np.uint8))

    def _compose_preview(self, plates: tuple[ChannelPlate, ...]) -> Image.Image:
        if not plates:
            raise ValueError("Separação não produziu canais.")
        height, width = plates[0].mask.shape
        background = 0.0 if self.config.dark_fabric else 1.0
        composite = np.full((height, width, 3), background, dtype=np.float32)
        for plate in plates:
            weight = plate.mask[..., None]
            ink = np.asarray(plate.color_rgb, dtype=np.float32) / 255.0
            composite = composite * (1.0 - weight) + ink * weight
        return Image.fromarray(
            (np.clip(composite, 0, 1) * 255).astype(np.uint8)
        )

    def _report(
        self,
        plates: tuple[ChannelPlate, ...],
        diagnostics: SeparationDiagnostics,
    ) -> str:
        engine_keys = ", ".join(self._profile.get("engine", {})) or "padrão"
        calibration = ", ".join(self._profile.get("calibration", {})) or "nenhuma"
        lines = [
            f"FAV8+: {len(plates)} canais | modo={diagnostics.archetype_resolution.resolved_mode} "
            f"({diagnostics.archetype_resolution.source}, "
            f"confiança={diagnostics.archetype_resolution.confidence:.3f}) | "
            f"tecido={'escuro' if self.config.dark_fabric else 'claro'} | "
            f"perfil Loop v2 | engine: {engine_keys} | calibração: {calibration}",
            f"Joint cleanup: {diagnostics.joint_cleanup.mode} | "
            f"área={diagnostics.joint_cleanup.effective_min_area_px}px | "
            f"componentes removidos={diagnostics.joint_cleanup.removed_components}",
            f"Contraste: {diagnostics.contrast_index:.3f} | "
            f"Chroma médio: {diagnostics.chroma_mean:.3f}",
            "Key plate: "
            + (
                f"{diagnostics.key_plate.mode} | "
                f"limiar={diagnostics.key_plate.effective_tonal_threshold:.3f} | "
                f"merge={','.join(diagnostics.key_plate.merged_channel_keys) or 'nenhum'}"
                if diagnostics.key_plate.enabled
                else "desativada (black original preservado)"
            ),
            "Canais ativos: " + ", ".join(diagnostics.active_channels),
        ]
        if self.config.sim_process.enabled:
            sim = self.config.sim_process
            lines.append(
                f"Sim process SS4: paleta fixa ({len(sim.palette)} tintas) | "
                f"lambda={sim.nnls_lambda:g} | ganhos={dict(sim.ink_gains) or 'nenhum'} | "
                f"underbase max={sim.underbase_max:g} gamma={sim.underbase_gamma:g}"
            )
        if diagnostics.pruned_channels:
            lines.append("Canais podados: " + ", ".join(diagnostics.pruned_channels))
        return "\n".join(lines)


def _smoothstep(value: np.ndarray) -> np.ndarray:
    clipped = np.clip(value, 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def _nnls_projected(
    basis: np.ndarray,
    targets: np.ndarray,
    penalty: np.ndarray,
    iterations: int,
    accelerated: bool = True,
) -> np.ndarray:
    """min ||basis·x − b||² + Σ penalty·x com 0 ≤ x ≤ 1, gradiente projetado vetorizado.

    A base (7 tintas em 3 canais) é singular; sem aceleração (FISTA) o método
    precisa de milhares de iterações para convergir.
    """
    gram = basis.T @ basis
    step = 1.0 / float(np.linalg.eigvalsh(gram).max())
    offset = targets @ basis - penalty
    solution = np.zeros((targets.shape[0], basis.shape[1]), dtype=np.float64)
    if not accelerated:
        for _ in range(iterations):
            solution -= step * (solution @ gram - offset)
            np.clip(solution, 0.0, 1.0, out=solution)
        return solution
    momentum_point = solution.copy()
    t = 1.0
    for _ in range(iterations):
        updated = np.clip(momentum_point - step * (momentum_point @ gram - offset), 0.0, 1.0)
        t_next = (1.0 + math.sqrt(1.0 + 4.0 * t * t)) / 2.0
        momentum_point = updated + ((t - 1.0) / t_next) * (updated - solution)
        solution, t = updated, t_next
    return solution


def _normalize(stack: np.ndarray) -> np.ndarray:
    total = stack.sum(axis=0, keepdims=True)
    return np.divide(
        stack, np.maximum(total, 1e-8), out=np.zeros_like(stack), where=total > 1e-8
    )
