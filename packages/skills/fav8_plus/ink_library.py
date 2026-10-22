"""Modelo e serialização da biblioteca imutável de tintas FAV8+."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np
from skimage.color import rgb2lab

INK_LIBRARY_SCHEMA_VERSION = 1
DEFAULT_LIBRARY_VERSION = "fav8-default-1"
VALID_ROLES = frozenset({"chromatic", "underbase", "highlight", "key", "neutral"})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _json_copy(value: Any, *, path: str = "metadados") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contém número não finito.")
        return value
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} deve usar apenas chaves string.")
            output[key] = _json_copy(item, path=f"{path}.{key}")
        return output
    if isinstance(value, (list, tuple)):
        return [_json_copy(item, path=f"{path}[]") for item in value]
    raise TypeError(f"{path} contém valor não serializável: {type(value).__name__}.")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class InkDefinition:
    """Definição imutável; Lab faz matching e RGB serve somente ao preview."""

    id: str
    nome: str
    lab_reference: tuple[float, float, float]
    display_rgb: tuple[int, int, int]
    role: str = "chromatic"
    metadados: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _ID_RE.fullmatch(self.id):
            raise ValueError(f"ID de tinta inválido: {self.id!r}.")
        if not isinstance(self.nome, str) or not self.nome.strip():
            raise ValueError("nome da tinta não pode ser vazio.")
        if self.role not in VALID_ROLES:
            raise ValueError(f"role de tinta inválido: {self.role!r}.")
        if len(self.lab_reference) != 3:
            raise ValueError("lab_reference deve ter três componentes.")
        lab = tuple(float(value) for value in self.lab_reference)
        if not all(math.isfinite(value) for value in lab):
            raise ValueError("lab_reference contém valor não finito.")
        if not 0.0 <= lab[0] <= 100.0 or not all(-128.0 <= value <= 127.0 for value in lab[1:]):
            raise ValueError("lab_reference está fora do gamut Lab aceito.")
        if len(self.display_rgb) != 3:
            raise ValueError("display_rgb deve ter três componentes.")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in self.display_rgb):
            raise TypeError("display_rgb deve conter valores numéricos.")
        if not all(math.isfinite(float(value)) for value in self.display_rgb):
            raise ValueError("display_rgb contém valor não finito.")
        rgb = tuple(int(round(min(255.0, max(0.0, float(value))))) for value in self.display_rgb)
        metadata = _json_copy(self.metadados)
        object.__setattr__(self, "nome", self.nome.strip())
        object.__setattr__(self, "lab_reference", lab)
        object.__setattr__(self, "display_rgb", rgb)
        object.__setattr__(self, "metadados", _freeze(metadata))

    @property
    def key(self) -> str:
        value = self.metadados.get("key")
        if isinstance(value, str) and value:
            return value
        return self.id.rsplit(":", 1)[-1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nome": self.nome,
            "lab_reference": list(self.lab_reference),
            "display_rgb": list(self.display_rgb),
            "role": self.role,
            "metadados": _thaw(self.metadados),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> InkDefinition:
        required = {"id", "nome", "lab_reference", "display_rgb", "role", "metadados"}
        unknown = set(value) - required
        missing = required - set(value)
        if missing or unknown:
            raise ValueError(
                f"Schema de tinta inválido; ausentes={sorted(missing)}, desconhecidos={sorted(unknown)}."
            )
        lab = value["lab_reference"]
        rgb = value["display_rgb"]
        if not isinstance(lab, (list, tuple)) or not isinstance(rgb, (list, tuple)):
            raise TypeError("lab_reference e display_rgb devem ser arrays.")
        metadata = value["metadados"]
        if not isinstance(metadata, Mapping):
            raise TypeError("metadados deve ser um objeto.")
        return cls(
            id=value["id"],
            nome=value["nome"],
            lab_reference=tuple(lab),  # type: ignore[arg-type]
            display_rgb=tuple(rgb),  # type: ignore[arg-type]
            role=value["role"],
            metadados=metadata,
        )


@dataclass(frozen=True, slots=True)
class InkLibrarySnapshot:
    """Snapshot completo, serializável e sem dependência de estado global."""

    version: str
    inks: tuple[InkDefinition, ...]
    schema_version: int = INK_LIBRARY_SCHEMA_VERSION
    hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != INK_LIBRARY_SCHEMA_VERSION
        ):
            raise ValueError(f"schema_version de biblioteca não suportado: {self.schema_version}.")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version da biblioteca não pode ser vazia.")
        inks = tuple(self.inks)
        if not inks:
            raise ValueError("A biblioteca deve conter ao menos uma tinta.")
        ids = [ink.id for ink in inks]
        keys = [ink.key for ink in inks]
        duplicate_ids = sorted({item for item in ids if ids.count(item) > 1})
        duplicate_keys = sorted({item for item in keys if keys.count(item) > 1})
        if duplicate_ids:
            raise ValueError(f"Conflitos de ID na biblioteca: {duplicate_ids}.")
        if duplicate_keys:
            raise ValueError(f"Conflitos de key na biblioteca: {duplicate_keys}.")
        object.__setattr__(self, "version", self.version.strip())
        object.__setattr__(self, "inks", inks)
        object.__setattr__(self, "hash", _snapshot_hash(self.schema_version, self.version, inks))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        output = {
            "schema_version": self.schema_version,
            "version": self.version,
            "inks": [ink.to_dict() for ink in self.inks],
        }
        if include_hash:
            output["hash"] = self.hash
        return output

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> InkLibrarySnapshot:
        allowed = {"schema_version", "version", "inks", "hash"}
        unknown = set(value) - allowed
        missing = {"schema_version", "version", "inks"} - set(value)
        if missing or unknown:
            raise ValueError(
                f"Schema de biblioteca inválido; ausentes={sorted(missing)}, "
                f"desconhecidos={sorted(unknown)}."
            )
        raw_inks = value["inks"]
        if not isinstance(raw_inks, list):
            raise TypeError("inks deve ser um array.")
        snapshot = cls(
            schema_version=value["schema_version"],
            version=value["version"],
            inks=tuple(
                InkDefinition.from_dict(item)
                if isinstance(item, Mapping)
                else _raise_ink_type()
                for item in raw_inks
            ),
        )
        expected = value.get("hash")
        if expected is not None and expected != snapshot.hash:
            raise ValueError("Hash da biblioteca não corresponde ao conteúdo.")
        return snapshot


def _raise_ink_type() -> InkDefinition:
    raise TypeError("Cada item de inks deve ser um objeto.")


def _snapshot_hash(schema_version: int, version: str, inks: tuple[InkDefinition, ...]) -> str:
    payload = {
        "schema_version": schema_version,
        "version": version,
        "inks": [ink.to_dict() for ink in inks],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    array = np.asarray(rgb, dtype=np.float64).reshape(1, 1, 3) / 255.0
    return tuple(round(float(item), 6) for item in rgb2lab(array).reshape(3))


_DEFAULT_SPECS: tuple[tuple[str, str, tuple[int, int, int], str, dict[str, Any]], ...] = (
    ("base_white", "Base White", (255, 255, 255), "underbase",
     {"gain": 1.0, "gamma": 1.35, "floor": 0.0, "ceiling": 0.95, "softness": 0.5}),
    ("highlight_white", "Highlight White", (255, 255, 252), "highlight",
     {"gain": 0.85, "gamma": 1.75, "floor": 0.04, "ceiling": 0.9, "softness": 0.4,
      "neighbors": ["gray"]}),
    ("black", "Black", (10, 10, 10), "key",
     {"gamma": 0.88, "floor": 0.04, "softness": 0.35,
      "neighbors": ["gray", "dark_blue", "purple", "brown_dark", "dark_green"]}),
    ("gray", "Gray", (140, 140, 140), "neutral",
     {"gain": 0.88, "gamma": 1.08, "floor": 0.045, "ceiling": 0.88, "softness": 0.9,
      "neighbors": ["black", "highlight_white"]}),
    ("red", "Red", (210, 30, 30), "chromatic",
     {"gain": 1.08, "gamma": 0.92, "floor": 0.055, "softness": 0.55,
      "hue_width": 38, "neighbors": ["orange", "pink", "purple", "brown_dark"]}),
    ("orange", "Orange", (230, 100, 15), "chromatic",
     {"gamma": 0.96, "floor": 0.05, "ceiling": 0.95, "hue_width": 40,
      "neighbors": ["gold_yellow", "red", "brown_light", "skin_mid"]}),
    ("gold_yellow", "Gold / Yellow", (220, 185, 15), "chromatic",
     {"gain": 1.03, "floor": 0.055, "ceiling": 0.95, "softness": 0.75,
      "hue_width": 39, "neighbors": ["orange", "green", "beige", "light_green"]}),
    ("blue", "Blue", (35, 80, 195), "chromatic",
     {"gain": 1.04, "gamma": 0.96, "floor": 0.055, "softness": 0.55,
      "neighbors": ["light_blue", "dark_blue", "turquoise", "purple"]}),
    ("green", "Green", (40, 160, 60), "chromatic",
     {"gamma": 0.96, "floor": 0.055, "ceiling": 0.95, "hue_width": 40,
      "neighbors": ["turquoise", "light_green", "dark_green", "gold_yellow"]}),
    ("turquoise", "Turquoise", (20, 180, 175), "chromatic",
     {"gain": 0.96, "floor": 0.055, "ceiling": 0.92, "softness": 0.8,
      "hue_width": 44, "neighbors": ["blue", "light_blue", "green"]}),
    ("purple", "Purple / Violet", (130, 35, 180), "chromatic",
     {"gain": 0.95, "floor": 0.055, "ceiling": 0.95,
      "neighbors": ["blue", "red", "pink", "dark_blue"]}),
    ("pink", "Pink", (230, 100, 150), "chromatic",
     {"gain": 0.82, "gamma": 1.08, "floor": 0.045, "ceiling": 0.86,
      "softness": 0.9, "hue_width": 38, "neighbors": ["red", "purple", "skin_light"]}),
    ("light_blue", "Light Blue", (110, 175, 240), "chromatic",
     {"gain": 0.86, "gamma": 1.08, "floor": 0.045, "ceiling": 0.88,
      "softness": 0.9, "hue_width": 38, "neighbors": ["blue", "turquoise"]}),
    ("dark_blue", "Dark Blue / Navy", (15, 30, 120), "chromatic",
     {"gamma": 0.9, "floor": 0.055, "ceiling": 0.95, "softness": 0.55,
      "hue_width": 40, "neighbors": ["blue", "purple", "black"]}),
    ("light_green", "Light Green", (130, 210, 80), "chromatic",
     {"gain": 0.86, "gamma": 1.05, "floor": 0.045, "ceiling": 0.88,
      "softness": 0.9, "hue_width": 38, "neighbors": ["green", "gold_yellow"]}),
    ("dark_green", "Dark Green", (20, 80, 30), "chromatic",
     {"gamma": 0.9, "floor": 0.052, "ceiling": 0.95, "softness": 0.65,
      "hue_width": 38, "neighbors": ["green", "black", "dark_blue", "brown_dark"]}),
    ("brown_light", "Brown Light", (165, 100, 45), "chromatic",
     {"gain": 0.95, "floor": 0.05, "ceiling": 0.92, "softness": 0.75,
      "neighbors": ["orange", "beige", "skin_mid", "brown_dark", "gold_yellow"]}),
    ("brown_dark", "Brown Dark", (90, 45, 10), "chromatic",
     {"gamma": 0.92, "floor": 0.05, "ceiling": 0.95, "softness": 0.65,
      "hue_width": 44, "neighbors": ["brown_light", "red", "orange", "black", "skin_shadow"]}),
    ("skin_light", "Skin Light", (255, 210, 170), "chromatic",
     {"gain": 0.82, "gamma": 1.12, "floor": 0.04, "ceiling": 0.85,
      "softness": 0.95, "hue_width": 44, "neighbors": ["beige", "pink", "skin_mid", "orange"]}),
    ("skin_mid", "Skin Mid", (220, 160, 110), "chromatic",
     {"gain": 0.9, "gamma": 1.04, "floor": 0.048, "ceiling": 0.9,
      "softness": 0.85, "hue_width": 44,
      "neighbors": ["orange", "brown_light", "pink", "skin_light", "skin_shadow", "beige"]}),
    ("skin_shadow", "Skin Shadow", (160, 100, 70), "chromatic",
     {"gain": 0.9, "gamma": 0.96, "floor": 0.048, "ceiling": 0.9,
      "softness": 0.75, "hue_width": 45,
      "neighbors": ["brown_dark", "red", "gray", "skin_mid", "brown_light"]}),
    ("beige", "Beige / Tan", (235, 210, 170), "chromatic",
     {"gain": 0.82, "gamma": 1.08, "floor": 0.04, "ceiling": 0.85,
      "softness": 0.9, "hue_width": 44,
      "neighbors": ["gold_yellow", "brown_light", "skin_light", "skin_mid"]}),
)


def default_ink_library() -> InkLibrarySnapshot:
    inks = []
    for key, nome, rgb, role, engine in _DEFAULT_SPECS:
        metadata = {
            "key": key,
            "export_name": key.upper(),
            "engine": engine,
            "origem": "paleta FAV8+ padrão",
        }
        inks.append(
            InkDefinition(
                id=f"fav8:{key}",
                nome=nome,
                lab_reference=_lab(rgb),
                display_rgb=rgb,
                role=role,
                metadados=metadata,
            )
        )
    return InkLibrarySnapshot(version=DEFAULT_LIBRARY_VERSION, inks=tuple(inks))
