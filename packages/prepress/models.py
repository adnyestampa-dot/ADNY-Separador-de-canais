"""Modelos imutáveis da camada opcional de pré-impressão."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping, TypeAlias

WhiteMode: TypeAlias = Literal["off", "underbase", "top_white", "both"]
WhitePolicy: TypeAlias = Literal[
    "reuse_existing", "replace_existing", "generate_if_missing"
]
InkMode: TypeAlias = Literal["knockout", "build_up"]
ScreenMode: TypeAlias = Literal["none", "am", "fm"]
CleanupMode: TypeAlias = Literal["off", "auto", "manual"]


@dataclass(frozen=True, slots=True)
class JointCleanupConfig:
    """Limpeza conjunta conservadora da união das chapas."""

    mode: CleanupMode = "off"
    threshold: float = 0.03
    min_area_px: int = 4
    dpi: float | None = None
    lpi: float | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"off", "auto", "manual"}:
            raise ValueError("mode de joint cleanup deve ser off, auto ou manual.")
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("threshold de joint cleanup deve estar entre 0 e 1.")
        if self.min_area_px < 1:
            raise ValueError("min_area_px de joint cleanup deve ser positivo.")
        if self.dpi is not None and self.dpi <= 0:
            raise ValueError("dpi de joint cleanup deve ser positivo.")
        if self.lpi is not None and self.lpi <= 0:
            raise ValueError("lpi de joint cleanup deve ser positivo.")


@dataclass(frozen=True, slots=True)
class WhiteConfig:
    mode: WhiteMode = "off"
    policy: WhitePolicy = "reuse_existing"
    choke_mm: float = 0.0
    min_density: float = 0.01

    def __post_init__(self) -> None:
        if self.policy not in {
            "reuse_existing",
            "replace_existing",
            "generate_if_missing",
        }:
            raise ValueError("policy de branco inválida.")
        if self.choke_mm < 0:
            raise ValueError("choke_mm não pode ser negativo.")
        if not 0 <= self.min_density <= 1:
            raise ValueError("min_density deve estar entre 0 e 1.")


@dataclass(frozen=True, slots=True)
class TrapConfig:
    enabled: bool = False
    spread_mm: float = 0.1
    roles: tuple[str, ...] = (
        "underbase",
        "chromatic",
        "process",
        "key",
        "neutral",
        "highlight",
    )

    def __post_init__(self) -> None:
        if self.spread_mm < 0:
            raise ValueError("spread_mm não pode ser negativo.")


@dataclass(frozen=True, slots=True)
class OverprintConfig:
    enabled: bool = False
    mode: InkMode = "knockout"
    reach_mm: float = 0.0

    def __post_init__(self) -> None:
        if self.reach_mm < 0:
            raise ValueError("reach_mm não pode ser negativo.")


@dataclass(frozen=True, slots=True)
class ToneCurveConfig:
    """Curva tonal independente da tecnologia de retícula."""

    enabled: bool = False
    gamma: float = 1.0
    gain: float = 0.0
    min_value: float = 0.0
    max_value: float = 1.0

    def __post_init__(self) -> None:
        if self.gamma <= 0:
            raise ValueError("gamma deve ser positivo.")
        if not -0.5 <= self.gain <= 0.5:
            raise ValueError("gain deve estar entre -0.5 e 0.5.")
        if not 0 <= self.min_value < self.max_value <= 1:
            raise ValueError("min_value/max_value devem satisfazer 0 <= min < max <= 1.")


@dataclass(frozen=True, slots=True)
class ScreenConfig:
    mode: ScreenMode = "none"
    lpi: float = 45.0
    fm_dot_um: float = 180.0
    default_angle: float = 22.5
    angles_by_role: Mapping[str, float] = field(
        default_factory=lambda: {
            "underbase": 22.5,
            "chromatic": 52.5,
            "process": 52.5,
            "key": 82.5,
            "neutral": 67.5,
            "highlight": 7.5,
        }
    )
    angles_by_channel: Mapping[str, float] = field(default_factory=dict)
    seed: int = 0

    def __post_init__(self) -> None:
        if self.mode not in {"none", "am", "fm"}:
            raise ValueError("mode de screening deve ser none, am ou fm.")
        if self.lpi <= 0 or self.fm_dot_um <= 0:
            raise ValueError("lpi e fm_dot_um devem ser positivos.")
        for name, angle in (
            ("default_angle", self.default_angle),
            *self.angles_by_role.items(),
            *self.angles_by_channel.items(),
        ):
            if not 0 <= float(angle) < 180:
                raise ValueError(f"Ângulo {name!r} deve estar entre 0 e 180 graus.")

    def angle_for(self, channel_key: str, role: str) -> float:
        return float(
            self.angles_by_channel.get(
                channel_key, self.angles_by_role.get(role, self.default_angle)
            )
        )


@dataclass(frozen=True, slots=True)
class FilmConfig:
    dpi: float = 300.0
    margin_mm: float = 12.0
    label: bool = True
    crop_marks: bool = True
    registration_marks: bool = True

    def __post_init__(self) -> None:
        if self.dpi <= 0:
            raise ValueError("dpi deve ser positivo.")
        if self.margin_mm < 0:
            raise ValueError("margin_mm não pode ser negativo.")


@dataclass(frozen=True, slots=True)
class PrepressConfig:
    """Defaults seguros: nenhuma transformação é aplicada implicitamente."""

    enabled: bool = False
    joint_cleanup: JointCleanupConfig = field(default_factory=JointCleanupConfig)
    white: WhiteConfig = field(default_factory=WhiteConfig)
    trapping: TrapConfig = field(default_factory=TrapConfig)
    overprint: OverprintConfig = field(default_factory=OverprintConfig)
    tone_curve: ToneCurveConfig = field(default_factory=ToneCurveConfig)
    screening: ScreenConfig = field(default_factory=ScreenConfig)
    film: FilmConfig = field(default_factory=FilmConfig)

    def to_dict(self) -> dict[str, Any]:
        """Representação JSON-safe para estado de sessão e manifests."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PrepressConfig:
        """Restaura configuração persistida, ignorando apenas a ausência de seções."""
        trapping = dict(value.get("trapping", {}))
        if "roles" in trapping:
            trapping["roles"] = tuple(trapping["roles"])
        return cls(
            enabled=bool(value.get("enabled", False)),
            joint_cleanup=JointCleanupConfig(**dict(value.get("joint_cleanup", {}))),
            white=WhiteConfig(**dict(value.get("white", {}))),
            trapping=TrapConfig(**trapping),
            overprint=OverprintConfig(**dict(value.get("overprint", {}))),
            tone_curve=ToneCurveConfig(**dict(value.get("tone_curve", {}))),
            screening=ScreenConfig(**dict(value.get("screening", {}))),
            film=FilmConfig(**dict(value.get("film", {}))),
        )
