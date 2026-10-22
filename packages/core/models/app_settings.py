from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AppSettings:
    recent_files: list[str] = field(default_factory=list)
    window_geometry: bytes | None = None
    window_state: bytes | None = None
    organization: str = "ADNY Separador"
    app_name: str = "ADNY Separador"
