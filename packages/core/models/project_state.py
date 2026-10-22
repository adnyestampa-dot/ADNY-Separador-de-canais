from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from packages.core.models.channel_info import ChannelInfo
from packages.core.models.image_document import ImageDocument
from packages.core.models.preview_display import PreviewDisplayMode
from packages.prepress.models import PrepressConfig


class TextilePreset(str, Enum):
    PRETO = "Preto"
    BRANCO = "Branco"
    CINZA_NEUTRO = "Cinza Neutro"
    MARINHO = "Marinho"


@dataclass
class ProjectState:
    active_document: ImageDocument | None = None
    result_document: ImageDocument | None = None
    channels: list[ChannelInfo] = field(default_factory=list)
    textile_preset: TextilePreset = TextilePreset.PRETO
    # Cor de ground personalizada (Edit > Change Ground Color); None = cor do preset.
    ground_rgb_override: tuple[int, int, int] | None = None
    # View > Show Textile Color: desligado, o preview mostra as separações sobre fundo neutro.
    show_textile_color: bool = True
    preview_display_mode: PreviewDisplayMode = PreviewDisplayMode.PROOF
    separation_params: dict[str, Any] = field(default_factory=dict)
    separation_document: ImageDocument | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    separation_manifest: dict[str, Any] = field(default_factory=dict)
    separation_diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def prepress_config(self) -> PrepressConfig | None:
        value = self.settings.get("prepress")
        return PrepressConfig.from_dict(value) if isinstance(value, dict) else None

    @prepress_config.setter
    def prepress_config(self, config: PrepressConfig | None) -> None:
        if config is None:
            self.settings.pop("prepress", None)
        else:
            self.settings["prepress"] = config.to_dict()

    def document_for_separation(self) -> ImageDocument | None:
        return self.separation_document or self.active_document

    def to_context_dict(self) -> dict[str, Any]:
        doc = self.active_document
        return {
            "has_document": doc is not None,
            "document_path": doc.path if doc else None,
            "resolution": f"{doc.width}x{doc.height}" if doc else None,
            "dpi": doc.dpi if doc else None,
            "channel_count": len(self.channels),
            "textile_preset": self.textile_preset.value,
            "separation_params": self.separation_params,
            "settings": self.settings,
        }
