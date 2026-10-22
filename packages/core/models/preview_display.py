from __future__ import annotations

from enum import Enum


class PreviewDisplayMode(str, Enum):
    """Modo de visualização inspirado em Separation Studio (ink / film / prova)."""

    INK = "ink"
    FILM = "film"
    PROOF = "proof"

    @classmethod
    def from_value(cls, value: str | None) -> PreviewDisplayMode:
        if value is None:
            return cls.PROOF
        try:
            return cls(value)
        except ValueError:
            return cls.PROOF
