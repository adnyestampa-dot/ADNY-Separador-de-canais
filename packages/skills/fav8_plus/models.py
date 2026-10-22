"""Contrato público, imutável e tipado do motor FAV8+."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping, TypeAlias

import numpy as np
import numpy.typing as npt
from PIL import Image

from packages.prepress.models import JointCleanupConfig
from packages.prepress.operations import JointCleanupReport
from packages.skills.fav8_plus.ink_library import (
    InkLibrarySnapshot,
    default_ink_library,
)

ResolvedFav8Mode: TypeAlias = Literal[
    "default",
    "oceano",
    "fogo",
    "natureza",
    "realismo",
    "quadrinhos",
]
Fav8Mode: TypeAlias = Literal[
    "auto",
    "default",
    "oceano",
    "fogo",
    "natureza",
    "realismo",
    "quadrinhos",
]
ArchetypeSource: TypeAlias = Literal["auto", "override"]
KeyPlateMode: TypeAlias = Literal["auto", "override"]
MeasurementSource: TypeAlias = Literal["none", "imported"]
PhysicalModel: TypeAlias = Literal["disabled"]
ImageInput: TypeAlias = Image.Image | str | Path | npt.NDArray[Any]

VALID_RESOLVED_MODES: tuple[ResolvedFav8Mode, ...] = (
    "default",
    "oceano",
    "fogo",
    "natureza",
    "realismo",
    "quadrinhos",
)
VALID_MODES: tuple[Fav8Mode, ...] = ("auto", *VALID_RESOLVED_MODES)


@dataclass(frozen=True, slots=True)
class KeyPlateConfig:
    """Extração opcional da chapa key usando o canal preto já existente."""

    enabled: bool = False
    mode: KeyPlateMode = "auto"
    tonal_threshold: float = 0.38
    gamma: float = 0.88
    chroma_protection: float = 0.035
    min_density: float = 0.0
    max_density: float = 1.0
    merge_compatible_dark: bool = False

    def __post_init__(self) -> None:
        if self.mode not in {"auto", "override"}:
            raise ValueError("mode da key plate deve ser auto ou override.")
        if not 0.0 < self.tonal_threshold <= 1.0:
            raise ValueError("tonal_threshold deve estar entre 0 (exclusivo) e 1.")
        if self.gamma <= 0:
            raise ValueError("gamma da key plate deve ser positivo.")
        if self.chroma_protection < 0:
            raise ValueError("chroma_protection não pode ser negativa.")
        if not 0.0 <= self.min_density <= self.max_density <= 1.0:
            raise ValueError("densidades da key plate devem satisfazer 0 <= min <= max <= 1.")


SimPaletteEntry: TypeAlias = tuple[str, str, str, tuple[int, int, int], str]

SIM_PROCESS_ROLES = frozenset({"underbase", "chromatic", "neutral", "highlight"})

# (key, label, export_name, rgb, role) na ordem de prensa do Separation Studio 4.
SS4_FIXED_PALETTE: tuple[SimPaletteEntry, ...] = (
    ("underbase", "#1 Underbase", "#1 Underbase", (254, 254, 254), "underbase"),
    ("red_032", "#2 Red 032", "#2 Red 032", (255, 0, 0), "chromatic"),
    ("blue_300", "#3 Blue 300", "#3 Blue 300", (0, 18, 255), "chromatic"),
    ("gold_123", "#4 Gold 123", "#4 Gold 123", (255, 198, 0), "chromatic"),
    ("purple_253", "#5 Purple 253", "#5 Purple 253", (255, 0, 200), "chromatic"),
    ("green_354", "#6 Green 354", "#6 Green 354", (0, 150, 0), "chromatic"),
    ("turquoise_312", "#7 Turquoise 312", "#7 Turquoise 312", (0, 167, 167), "chromatic"),
    ("gray_c8", "#8 Gray C8", "#8 Gray C8", (150, 150, 150), "neutral"),
    ("top_white", "#9 Top White", "#9 Top White", (252, 255, 255), "highlight"),
)


def _float_items(name: str, value: Any) -> tuple[tuple[str, float], ...]:
    items = value.items() if isinstance(value, Mapping) else value
    output: dict[str, float] = {}
    for key, raw in items:
        if not isinstance(key, str) or isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise TypeError(f"{name} deve mapear key de tinta → número.")
        number = float(raw)
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{name}[{key!r}] deve ser finito e não negativo.")
        output[key] = number
    return tuple(sorted(output.items()))


# Cores efetivas das tintas no proof do SS4. Passam de 255 porque a tinta sobre
# o underbase clareia; o clip acontece só na soma final do preview.
SS4_PREVIEW_INK_RGB: tuple[tuple[str, tuple[float, float, float]], ...] = (
    ("blue_300", (53.0, 51.0, 230.0)),
    ("gold_123", (318.0, 277.0, 98.0)),
    ("gray_c8", (199.0, 201.0, 201.0)),
    ("green_354", (8.0, 134.0, 24.0)),
    ("purple_253", (284.0, 0.0, 50.0)),
    ("red_032", (282.0, 81.0, 84.0)),
    ("top_white", (272.0, 286.0, 294.0)),
    ("turquoise_312", (158.0, 250.0, 222.0)),
)

PREVIEW_INK_MAX = 1020.0

# O SS4 não usa Turquoise em magentas/roxos nem em amarelos.
SS4_INK_HUE_GATES: tuple[tuple[str, tuple[float, float, float]], ...] = (
    ("turquoise_312", (150.0, 250.0, 40.0)),
)

# O SS4 imprime ~0.78× a Gold e 1.1–1.2× o Red que o NNLS em sRGB dá, de forma
# constante em matiz, L* e C*; Turquoise e Blue também saem mais densos.
SS4_INK_GAINS: tuple[tuple[str, float], ...] = (
    ("blue_300", 1.5),
    ("gold_123", 0.78),
    ("red_032", 1.2),
    ("top_white", 1.15),
    ("turquoise_312", 1.3),
)

# Purple 253 decompõe vermelhos/peles junto com Gold no lugar do Red 032;
# o SS4 quase não usa Purple, então ele leva penalidade L1 maior. Com
# λ_turquoise >= 0.04 o Turquoise some por completo.
SS4_INK_LAMBDAS: tuple[tuple[str, float], ...] = (
    ("purple_253", 0.08),
    ("turquoise_312", 0.03),
)


def _rgb_items(name: str, value: Any) -> tuple[tuple[str, tuple[float, float, float]], ...]:
    items = value.items() if isinstance(value, Mapping) else value
    output: dict[str, tuple[float, float, float]] = {}
    for key, raw in items:
        if not isinstance(key, str) or isinstance(raw, (str, bytes)):
            raise TypeError(f"{name} deve mapear key de tinta → [r, g, b].")
        rgb = tuple(raw)
        if len(rgb) != 3 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) for v in rgb
        ):
            raise TypeError(f"{name}[{key!r}] deve ter três números.")
        numbers = tuple(float(v) for v in rgb)
        if not all(math.isfinite(v) and 0.0 <= v <= PREVIEW_INK_MAX for v in numbers):
            raise ValueError(f"{name}[{key!r}] deve ter valores entre 0 e {PREVIEW_INK_MAX:g}.")
        output[key] = numbers  # type: ignore[assignment]
    return tuple(sorted(output.items()))


def _hue_gate_items(
    name: str, value: Any
) -> tuple[tuple[str, tuple[float, float, float]], ...]:
    items = value.items() if isinstance(value, Mapping) else value
    output: dict[str, tuple[float, float, float]] = {}
    for key, raw in items:
        if not isinstance(key, str) or isinstance(raw, (str, bytes)):
            raise TypeError(f"{name} deve mapear key de tinta → [h0, h1, borda].")
        gate = tuple(raw)
        if len(gate) != 3 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) for v in gate
        ):
            raise TypeError(f"{name}[{key!r}] deve ter três números: h0, h1 e borda.")
        low, high, soft = (float(v) for v in gate)
        if not all(math.isfinite(v) for v in (low, high, soft)):
            raise ValueError(f"{name}[{key!r}] deve ser finito.")
        if not (low < high <= low + 360.0) or soft <= 0:
            raise ValueError(f"{name}[{key!r}] exige h0 < h1 <= h0 + 360 e borda positiva.")
        output[key] = (low, high, soft)
    return tuple(sorted(output.items()))


@dataclass(frozen=True, slots=True)
class SimProcessConfig:
    """Simulated Process estilo Separation Studio 4 (camiseta escura, paleta fixa).

    Desligado por padrão: com ``enabled=False`` o motor segue o caminho FAV8 original.
    """

    enabled: bool = False
    palette: tuple[SimPaletteEntry, ...] = SS4_FIXED_PALETTE
    garment_rgb: tuple[int, int, int] | None = (0, 0, 0)
    knockout_tolerance: float = 0.06
    nnls_lambda: float = 0.02
    ink_lambdas: tuple[tuple[str, float], ...] = SS4_INK_LAMBDAS
    nnls_iters: int = 400
    nnls_solver: Literal["fista", "pg"] = "fista"
    color_bits: int = 6
    ink_floor: float = 0.03
    min_plate_coverage: float = 0.004
    ink_gains: tuple[tuple[str, float], ...] = SS4_INK_GAINS
    # key → (h0, h1, borda) em graus do matiz Lab: fora do intervalo a densidade
    # cai por smoothstep até zero a ``borda`` graus. O NNLS não é refeito.
    ink_hue_gates: tuple[tuple[str, tuple[float, float, float]], ...] = SS4_INK_HUE_GATES
    top_white_neutral_boost: float = 0.0
    gray_gain: float = 0.45
    gray_l_mid: float = 55.0
    gray_width: float = 55.0
    gray_chroma_max: float = 40.0
    # Portão de croma do Gray em função de L*: cmax = max(gray_chroma_max +
    # slope·(L*−50), 1). O SS4 corta o Gray cedo nos escuros e tarde nos claros.
    gray_chroma_slope: float = 0.7
    gray_residual_weight: float = 1.9
    underbase_max: float = 0.75
    underbase_v0: float = 0.20
    underbase_v1: float = 0.95
    underbase_gamma: float = 1.3
    underbase_choke_px: int = 0
    preview: Literal["additive", "over"] = "additive"
    # key → RGB efetivo no preview aditivo (0..1020). Tinta do mapa ignora
    # gray_residual_weight; mapa vazio = cor da paleta.
    preview_ink_rgb: tuple[tuple[str, tuple[float, float, float]], ...] = SS4_PREVIEW_INK_RGB

    def __post_init__(self) -> None:
        palette = tuple(
            (str(key), str(label), str(export), tuple(int(v) for v in rgb), str(role))
            for key, label, export, rgb, role in self.palette
        )
        keys = [entry[0] for entry in palette]
        if len(keys) != len(set(keys)) or not keys:
            raise ValueError("palette do sim_process deve ter keys únicas e não vazias.")
        for key, label, export, rgb, role in palette:
            if not key or not label or not export:
                raise ValueError("palette do sim_process exige key, label e export_name.")
            if len(rgb) != 3 or not all(0 <= v <= 255 for v in rgb):
                raise ValueError(f"RGB inválido para {key!r}.")
            if role not in SIM_PROCESS_ROLES:
                raise ValueError(
                    f"role {role!r} inválido em {key!r}; aceitos: {sorted(SIM_PROCESS_ROLES)}."
                )
        roles = [entry[4] for entry in palette]
        for role in ("underbase", "neutral", "highlight"):
            if roles.count(role) > 1:
                raise ValueError(f"palette do sim_process aceita no máximo uma tinta {role}.")
        if not any(role in {"chromatic", "highlight"} for role in roles):
            raise ValueError("palette do sim_process precisa de ao menos uma tinta de cor.")
        object.__setattr__(self, "palette", palette)

        if self.garment_rgb is not None:
            garment = tuple(int(v) for v in self.garment_rgb)
            if len(garment) != 3 or not all(0 <= v <= 255 for v in garment):
                raise ValueError("garment_rgb deve ter três inteiros entre 0 e 255.")
            object.__setattr__(self, "garment_rgb", garment)
        gains = _float_items("ink_gains", self.ink_gains)
        if self.ink_gains is SS4_INK_GAINS:
            gains = tuple(item for item in gains if item[0] in keys)
        lambdas = _float_items("ink_lambdas", self.ink_lambdas)
        if self.ink_lambdas is SS4_INK_LAMBDAS:
            lambdas = tuple(item for item in lambdas if item[0] in keys)
        for name, items in (("ink_gains", gains), ("ink_lambdas", lambdas)):
            unknown = {key for key, _ in items} - set(keys)
            if unknown:
                raise ValueError(f"{name} com tintas fora da palette: {sorted(unknown)}")
        object.__setattr__(self, "ink_gains", gains)
        object.__setattr__(self, "ink_lambdas", lambdas)
        preview_rgb = _rgb_items("preview_ink_rgb", self.preview_ink_rgb)
        if self.preview_ink_rgb is SS4_PREVIEW_INK_RGB:
            preview_rgb = tuple(item for item in preview_rgb if item[0] in keys)
        unknown = {key for key, _ in preview_rgb} - set(keys)
        if unknown:
            raise ValueError(f"preview_ink_rgb com tintas fora da palette: {sorted(unknown)}")
        object.__setattr__(self, "preview_ink_rgb", preview_rgb)
        hue_gates = _hue_gate_items("ink_hue_gates", self.ink_hue_gates)
        if self.ink_hue_gates is SS4_INK_HUE_GATES:
            hue_gates = tuple(item for item in hue_gates if item[0] in keys)
        gated = {key for key, _ in hue_gates}
        if gated - set(keys):
            raise ValueError(f"ink_hue_gates com tintas fora da palette: {sorted(gated - set(keys))}")
        if any(entry[4] == "underbase" for entry in palette if entry[0] in gated):
            raise ValueError("ink_hue_gates não se aplica ao underbase.")
        object.__setattr__(self, "ink_hue_gates", hue_gates)

        if not 0.0 <= self.knockout_tolerance <= 1.0:
            raise ValueError("knockout_tolerance deve estar entre 0 e 1.")
        if self.nnls_lambda < 0:
            raise ValueError("nnls_lambda não pode ser negativo.")
        if self.nnls_iters < 1:
            raise ValueError("nnls_iters deve ser positivo.")
        if self.nnls_solver not in {"fista", "pg"}:
            raise ValueError("nnls_solver deve ser fista ou pg.")
        if not 4 <= self.color_bits <= 8:
            raise ValueError("color_bits deve estar entre 4 e 8.")
        if not 0.0 <= self.ink_floor < 1.0:
            raise ValueError("ink_floor deve estar em [0, 1).")
        if not 0.0 <= self.min_plate_coverage <= 1.0:
            raise ValueError("min_plate_coverage deve estar entre 0 e 1.")
        if self.top_white_neutral_boost < 0:
            raise ValueError("top_white_neutral_boost não pode ser negativo.")
        if not 0.0 <= self.gray_gain <= 1.0:
            raise ValueError("gray_gain deve estar entre 0 e 1.")
        if self.gray_width <= 0 or self.gray_chroma_max <= 0:
            raise ValueError("gray_width e gray_chroma_max devem ser positivos.")
        if isinstance(self.gray_chroma_slope, bool) or not math.isfinite(self.gray_chroma_slope):
            raise ValueError("gray_chroma_slope deve ser um número finito.")
        if self.gray_residual_weight < 0:
            raise ValueError("gray_residual_weight não pode ser negativo.")
        if not 0.0 <= self.underbase_max <= 1.0:
            raise ValueError("underbase_max deve estar entre 0 e 1.")
        if not 0.0 <= self.underbase_v0 < self.underbase_v1 <= 1.0:
            raise ValueError("underbase exige 0 <= v0 < v1 <= 1.")
        if self.underbase_gamma <= 0:
            raise ValueError("underbase_gamma deve ser positivo.")
        if self.underbase_choke_px < 0:
            raise ValueError("underbase_choke_px não pode ser negativo.")
        if self.preview not in {"additive", "over"}:
            raise ValueError("preview do sim_process deve ser additive ou over.")

    @property
    def gains(self) -> dict[str, float]:
        return dict(self.ink_gains)

    @property
    def lambdas(self) -> dict[str, float]:
        return dict(self.ink_lambdas)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "palette": [
                [key, label, export, list(rgb), role]
                for key, label, export, rgb, role in self.palette
            ],
            "garment_rgb": list(self.garment_rgb) if self.garment_rgb is not None else None,
            "knockout_tolerance": self.knockout_tolerance,
            "nnls_lambda": self.nnls_lambda,
            "ink_lambdas": dict(self.ink_lambdas),
            "nnls_iters": self.nnls_iters,
            "nnls_solver": self.nnls_solver,
            "color_bits": self.color_bits,
            "ink_floor": self.ink_floor,
            "min_plate_coverage": self.min_plate_coverage,
            "ink_gains": dict(self.ink_gains),
            "ink_hue_gates": {key: list(gate) for key, gate in self.ink_hue_gates},
            "top_white_neutral_boost": self.top_white_neutral_boost,
            "gray_gain": self.gray_gain,
            "gray_l_mid": self.gray_l_mid,
            "gray_width": self.gray_width,
            "gray_chroma_max": self.gray_chroma_max,
            "gray_chroma_slope": self.gray_chroma_slope,
            "gray_residual_weight": self.gray_residual_weight,
            "underbase_max": self.underbase_max,
            "underbase_v0": self.underbase_v0,
            "underbase_v1": self.underbase_v1,
            "underbase_gamma": self.underbase_gamma,
            "underbase_choke_px": self.underbase_choke_px,
            "preview": self.preview,
            "preview_ink_rgb": {key: list(rgb) for key, rgb in self.preview_ink_rgb},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | bool | None) -> SimProcessConfig:
        if value is None or value is False:
            return cls()
        if value is True:
            return cls(enabled=True)
        if not isinstance(value, Mapping):
            raise TypeError("sim_process deve ser booleano ou objeto.")
        allowed = {item for item in cls.__dataclass_fields__}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"Campos de sim_process desconhecidos: {sorted(unknown)}")
        data = dict(value)
        if "palette" in data:
            data["palette"] = tuple(
                (key, label, export, tuple(rgb), role)
                for key, label, export, rgb, role in data["palette"]
            )
        if data.get("garment_rgb") is not None:
            data["garment_rgb"] = tuple(data["garment_rgb"])
        if "enabled" in data and not isinstance(data["enabled"], bool):
            raise TypeError("sim_process.enabled deve ser booleano.")
        return cls(**data)


@dataclass(frozen=True, slots=True)
class MeasurementProvenance:
    """Condições declaradas de uma futura medição física."""

    instrument: str | None = None
    geometry: str | None = None
    illuminant: str | None = None
    mesh: str | None = None
    ink: str | None = None
    fabric: str | None = None
    emulsion: str | None = None
    cure: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "instrument",
            "geometry",
            "illuminant",
            "mesh",
            "ink",
            "fabric",
            "emulsion",
            "cure",
        ):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"provenance.{name} deve ser uma string não vazia.")

    @property
    def is_complete(self) -> bool:
        return all(
            getattr(self, name) is not None
            for name in (
                "instrument",
                "geometry",
                "illuminant",
                "mesh",
                "ink",
                "fabric",
                "emulsion",
                "cure",
            )
        )

    def to_dict(self) -> dict[str, str | None]:
        return {
            "instrument": self.instrument,
            "geometry": self.geometry,
            "illuminant": self.illuminant,
            "mesh": self.mesh,
            "ink": self.ink,
            "fabric": self.fabric,
            "emulsion": self.emulsion,
            "cure": self.cure,
        }


@dataclass(frozen=True, slots=True)
class MeasuredInkLab:
    """Lab medido de uma tinta, apenas para transporte de metadados."""

    ink_id: str
    lab: tuple[float, float, float]

    def __post_init__(self) -> None:
        if not isinstance(self.ink_id, str) or not self.ink_id.strip():
            raise ValueError("ink_id medido deve ser uma string não vazia.")
        values = tuple(float(value) for value in self.lab)
        if len(values) != 3 or not all(math.isfinite(value) for value in values):
            raise ValueError("Lab de tinta deve conter três números finitos.")
        if not 0.0 <= values[0] <= 100.0:
            raise ValueError("L* de tinta deve estar entre 0 e 100.")
        object.__setattr__(self, "lab", values)

    def to_dict(self) -> dict[str, Any]:
        return {"ink_id": self.ink_id, "lab": list(self.lab)}


@dataclass(frozen=True, slots=True)
class PhysicalMeasurementProfile:
    """Gancho versionado; nesta fase nunca altera separação, preview ou export."""

    schema_version: int = 1
    measurement_profile_id: str | None = None
    source: MeasurementSource = "none"
    physical_model: PhysicalModel = "disabled"
    measured_gain_curve: tuple[tuple[float, float], ...] | None = None
    ink_labs: tuple[MeasuredInkLab, ...] | None = None
    substrate_lab: tuple[float, float, float] | None = None
    provenance: MeasurementProvenance | None = None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("schema_version físico não suportado; esperado 1.")
        if self.source not in {"none", "imported"}:
            raise ValueError("source físico deve ser none ou imported.")
        if self.physical_model != "disabled":
            raise ValueError(
                "physical_model deve ser disabled; modelos físicos ainda não são suportados."
            )
        if self.measurement_profile_id is not None and (
            not isinstance(self.measurement_profile_id, str)
            or not self.measurement_profile_id.strip()
        ):
            raise ValueError("measurement_profile_id deve ser uma string não vazia.")
        if self.provenance is not None and not isinstance(
            self.provenance, MeasurementProvenance
        ):
            raise TypeError("provenance deve ser um MeasurementProvenance imutável.")

        curve = self.measured_gain_curve
        if curve is not None:
            normalized = tuple((float(x), float(y)) for x, y in curve)
            if len(normalized) < 2:
                raise ValueError("measured_gain_curve deve ter ao menos dois pontos.")
            if not all(
                math.isfinite(x)
                and math.isfinite(y)
                and 0.0 <= x <= 1.0
                and 0.0 <= y <= 1.0
                for x, y in normalized
            ):
                raise ValueError("Pontos da curva de ganho devem ser finitos entre 0 e 1.")
            if any(left[0] >= right[0] for left, right in zip(normalized, normalized[1:])):
                raise ValueError("Entradas da curva de ganho devem ser estritamente crescentes.")
            object.__setattr__(self, "measured_gain_curve", normalized)

        if self.ink_labs is not None:
            normalized_inks = tuple(self.ink_labs)
            if not normalized_inks or not all(
                isinstance(item, MeasuredInkLab) for item in normalized_inks
            ):
                raise ValueError("ink_labs deve conter ao menos uma medição MeasuredInkLab.")
            ids = [item.ink_id for item in normalized_inks]
            if len(ids) != len(set(ids)):
                raise ValueError("ink_labs não pode repetir ink_id.")
            object.__setattr__(self, "ink_labs", normalized_inks)

        if self.substrate_lab is not None:
            substrate = tuple(float(value) for value in self.substrate_lab)
            if len(substrate) != 3 or not all(math.isfinite(value) for value in substrate):
                raise ValueError("substrate_lab deve conter três números finitos.")
            if not 0.0 <= substrate[0] <= 100.0:
                raise ValueError("L* do substrato deve estar entre 0 e 100.")
            object.__setattr__(self, "substrate_lab", substrate)

        payload_fields = (
            self.measurement_profile_id,
            self.measured_gain_curve,
            self.ink_labs,
            self.substrate_lab,
            self.provenance,
        )
        if self.source == "none" and any(value is not None for value in payload_fields):
            raise ValueError("source none exige ausência completa de dados medidos.")
        if self.source == "imported":
            missing = [
                name
                for name, value in (
                    ("measurement_profile_id", self.measurement_profile_id),
                    ("measured_gain_curve", self.measured_gain_curve),
                    ("ink_labs", self.ink_labs),
                    ("substrate_lab", self.substrate_lab),
                    ("provenance", self.provenance),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    "Perfil físico imported incompleto; faltam: " + ", ".join(missing) + "."
                )
            assert self.provenance is not None
            if not self.provenance.is_complete:
                raise ValueError("Perfil físico imported exige proveniência completa.")

    @property
    def present(self) -> bool:
        return self.source == "imported"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "measurement_profile_id": self.measurement_profile_id,
            "source": self.source,
            "physical_model": self.physical_model,
            "present": self.present,
            "measured_gain_curve": (
                [list(point) for point in self.measured_gain_curve]
                if self.measured_gain_curve is not None
                else None
            ),
            "ink_labs": (
                [measurement.to_dict() for measurement in self.ink_labs]
                if self.ink_labs is not None
                else None
            ),
            "substrate_lab": (
                list(self.substrate_lab) if self.substrate_lab is not None else None
            ),
            "provenance": self.provenance.to_dict() if self.provenance is not None else None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PhysicalMeasurementProfile:
        if not isinstance(value, Mapping):
            raise TypeError("Perfil físico deve ser um objeto.")
        allowed = {
            "schema_version",
            "measurement_profile_id",
            "source",
            "physical_model",
            "present",
            "measured_gain_curve",
            "ink_labs",
            "substrate_lab",
            "provenance",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"Campos físicos desconhecidos: {sorted(unknown)}")
        provenance_data = value.get("provenance")
        ink_data = value.get("ink_labs")
        return cls(
            schema_version=int(value.get("schema_version", 1)),
            measurement_profile_id=value.get("measurement_profile_id"),
            source=value.get("source", "none"),
            physical_model=value.get("physical_model", "disabled"),
            measured_gain_curve=(
                tuple(tuple(point) for point in value["measured_gain_curve"])
                if value.get("measured_gain_curve") is not None
                else None
            ),
            ink_labs=(
                tuple(
                    MeasuredInkLab(ink_id=item["ink_id"], lab=tuple(item["lab"]))
                    for item in ink_data
                )
                if ink_data is not None
                else None
            ),
            substrate_lab=(
                tuple(value["substrate_lab"])
                if value.get("substrate_lab") is not None
                else None
            ),
            provenance=(
                MeasurementProvenance(**dict(provenance_data))
                if provenance_data is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class Fav8Config:
    """Configuração por instância; não altera estado global."""

    mode: Fav8Mode = "auto"
    dark_fabric: bool = True
    smart_pruning: bool = True
    max_clusters: int = 10
    analysis_max_size: int = 720
    min_channel_score: float = 0.18
    min_coverage_estimate: float = 0.006
    max_active_chromatic: int | None = None
    min_active_chromatic: int | None = None
    include_specials: bool = True
    debug: bool = False
    tune_profile: Path | None = None
    ink_library: InkLibrarySnapshot = field(default_factory=default_ink_library)
    ink_library_snapshot: InkLibrarySnapshot | None = field(
        default=None, repr=False, compare=False
    )
    key_plate: KeyPlateConfig = field(default_factory=KeyPlateConfig)
    joint_cleanup: JointCleanupConfig = field(default_factory=JointCleanupConfig)
    physical_measurement: PhysicalMeasurementProfile = field(
        default_factory=PhysicalMeasurementProfile
    )
    sim_process: SimProcessConfig = field(default_factory=SimProcessConfig)

    def __post_init__(self) -> None:
        if not isinstance(self.sim_process, SimProcessConfig):
            raise TypeError("sim_process deve ser um SimProcessConfig.")
        if self.ink_library_snapshot is not None:
            if not isinstance(self.ink_library_snapshot, InkLibrarySnapshot):
                raise TypeError(
                    "ink_library_snapshot deve ser um InkLibrarySnapshot imutável."
                )
            object.__setattr__(self, "ink_library", self.ink_library_snapshot)
        if not isinstance(self.ink_library, InkLibrarySnapshot):
            raise TypeError("ink_library deve ser um InkLibrarySnapshot imutável.")
        if not isinstance(self.physical_measurement, PhysicalMeasurementProfile):
            raise TypeError("physical_measurement deve ser um PhysicalMeasurementProfile.")
        if self.mode not in VALID_MODES:
            raise ValueError(
                f"Modo FAV8+ inválido: {self.mode!r}. "
                f"Valores aceitos: {', '.join(VALID_MODES)}."
            )
        if not 1 <= self.max_clusters <= 16:
            raise ValueError("max_clusters deve estar entre 1 e 16.")
        if self.analysis_max_size < 1:
            raise ValueError("analysis_max_size deve ser positivo.")
        if not 0.0 <= self.min_channel_score <= 1.0:
            raise ValueError("min_channel_score deve estar entre 0 e 1.")
        if not 0.0 <= self.min_coverage_estimate <= 1.0:
            raise ValueError("min_coverage_estimate deve estar entre 0 e 1.")
        for name, value in (
            ("max_active_chromatic", self.max_active_chromatic),
            ("min_active_chromatic", self.min_active_chromatic),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} não pode ser negativo.")


@dataclass(frozen=True, slots=True)
class ChannelPlate:
    """Uma chapa spot produzida pelo motor."""

    key: str
    label: str
    export_name: str
    color_rgb: tuple[int, int, int]
    mask: npt.NDArray[np.float32] = field(repr=False, compare=False)
    id: str = ""
    role: str = "chromatic"

    def __post_init__(self) -> None:
        mask = np.asarray(self.mask, dtype=np.float32)
        if mask.ndim != 2:
            raise ValueError(f"Máscara de {self.key!r} deve ser bidimensional.")
        if not np.isfinite(mask).all():
            raise ValueError(f"Máscara de {self.key!r} contém valores não finitos.")
        frozen = np.clip(mask, 0.0, 1.0).astype(np.float32, copy=True)
        frozen.setflags(write=False)
        object.__setattr__(self, "mask", frozen)
        if not self.id:
            object.__setattr__(self, "id", f"fav8:{self.key}")


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    key: str
    label: str
    export_name: str
    color_rgb: tuple[int, int, int]
    print_index: int
    is_special: bool
    id: str = ""
    role: str = "chromatic"

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", f"fav8:{self.key}")


@dataclass(frozen=True, slots=True)
class ArtworkDNA:
    """Assinatura objetiva e reproduzível da área visível da arte em Lab."""

    dominant_families: tuple[tuple[str, float], ...]
    tonal_distribution: tuple[tuple[str, float], ...]
    contrast_index: float
    chroma_mean: float
    visible_fraction: float
    has_highlight: bool
    has_deep_black: bool
    has_colored_dark: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "dominant_families": [list(item) for item in self.dominant_families],
            "tonal_distribution": [list(item) for item in self.tonal_distribution],
            "contrast_index": self.contrast_index,
            "chroma_mean": self.chroma_mean,
            "visible_fraction": self.visible_fraction,
            "has_highlight": self.has_highlight,
            "has_deep_black": self.has_deep_black,
            "has_colored_dark": self.has_colored_dark,
        }


@dataclass(frozen=True, slots=True)
class ArchetypeResolution:
    """Modo efetivo e proveniência da decisão automática ou manual."""

    requested_mode: Fav8Mode
    resolved_mode: ResolvedFav8Mode
    confidence: float
    reasons: tuple[str, ...]
    source: ArchetypeSource

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence deve estar entre 0 e 1.")
        if self.resolved_mode not in VALID_RESOLVED_MODES:
            raise ValueError(f"Arquétipo resolvido inválido: {self.resolved_mode!r}.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_mode": self.requested_mode,
            "resolved_mode": self.resolved_mode,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class KeyPlateReport:
    enabled: bool
    mode: KeyPlateMode
    effective_tonal_threshold: float
    merged_channel_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "effective_tonal_threshold": self.effective_tonal_threshold,
            "merged_channel_keys": list(self.merged_channel_keys),
        }


@dataclass(frozen=True, slots=True)
class SeparationManifest:
    engine: str
    engine_version: str
    mode: ResolvedFav8Mode
    dark_fabric: bool
    width: int
    height: int
    channels: tuple[ManifestEntry, ...]
    tune_source: str
    artwork_dna: ArtworkDNA
    archetype_resolution: ArchetypeResolution
    joint_cleanup: JointCleanupReport
    key_plate: KeyPlateReport
    physical_measurement: PhysicalMeasurementProfile = field(
        default_factory=PhysicalMeasurementProfile
    )
    manifest_version: int = 3
    profile_schema_version: int = 1
    profile_version: str = "unknown"
    profile_hash: str = ""
    ink_library_schema_version: int = 1
    ink_library_version: str = "unknown"
    ink_library_hash: str = ""
    ink_library_snapshot: Mapping[str, Any] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "ink_library_snapshot", _freeze_mapping(self.ink_library_snapshot)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "profile_schema_version": self.profile_schema_version,
            "profile_version": self.profile_version,
            "profile_hash": self.profile_hash,
            "ink_library_schema_version": self.ink_library_schema_version,
            "ink_library_version": self.ink_library_version,
            "ink_library_hash": self.ink_library_hash,
            "ink_library_snapshot": _json_value(self.ink_library_snapshot),
            "mode": self.mode,
            "dark_fabric": self.dark_fabric,
            "width": self.width,
            "height": self.height,
            "channels": [
                {
                    "id": item.id,
                    "key": item.key,
                    "label": item.label,
                    "export_name": item.export_name,
                    "role": item.role,
                    "color_rgb": list(item.color_rgb),
                    "print_index": item.print_index,
                    "is_special": item.is_special,
                }
                for item in self.channels
            ],
            "tune_source": self.tune_source,
            "artwork_dna": self.artwork_dna.to_dict(),
            "archetype_resolution": self.archetype_resolution.to_dict(),
            "joint_cleanup": self.joint_cleanup.to_dict(),
            "key_plate": self.key_plate.to_dict(),
            "physical_measurement": self.physical_measurement.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SeparationDiagnostics:
    active_channels: tuple[str, ...]
    pruned_channels: tuple[str, ...]
    dominant_families: tuple[tuple[str, float], ...]
    tonal_distribution: tuple[tuple[str, float], ...]
    contrast_index: float
    chroma_mean: float
    notes: tuple[str, ...]
    artwork_dna: ArtworkDNA
    archetype_resolution: ArchetypeResolution
    joint_cleanup: JointCleanupReport
    key_plate: KeyPlateReport
    profile: Mapping[str, Any] = field(repr=False, compare=False)
    ink_library_schema_version: int = 1
    ink_library_version: str = "unknown"
    ink_library_hash: str = ""
    ink_library_snapshot: Mapping[str, Any] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile", _freeze_mapping(self.profile))
        object.__setattr__(
            self, "ink_library_snapshot", _freeze_mapping(self.ink_library_snapshot)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_channels": list(self.active_channels),
            "pruned_channels": list(self.pruned_channels),
            "dominant_families": [list(item) for item in self.dominant_families],
            "tonal_distribution": [list(item) for item in self.tonal_distribution],
            "contrast_index": self.contrast_index,
            "chroma_mean": self.chroma_mean,
            "notes": list(self.notes),
            "profile": _json_value(self.profile),
            "ink_library_schema_version": self.ink_library_schema_version,
            "ink_library_version": self.ink_library_version,
            "ink_library_hash": self.ink_library_hash,
            "ink_library_snapshot": _json_value(self.ink_library_snapshot),
            "artwork_dna": self.artwork_dna.to_dict(),
            "archetype_resolution": self.archetype_resolution.to_dict(),
            "joint_cleanup": self.joint_cleanup.to_dict(),
            "key_plate": self.key_plate.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SeparationResult:
    plates: tuple[ChannelPlate, ...]
    preview: Image.Image = field(compare=False)
    manifest: SeparationManifest
    diagnostics: SeparationDiagnostics
    report: str

    @property
    def channels(self) -> Mapping[str, npt.NDArray[np.float32]]:
        return MappingProxyType({plate.key: plate.mask for plate in self.plates})


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {str(key): _freeze_value(item) for key, item in value.items()}
    )


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
