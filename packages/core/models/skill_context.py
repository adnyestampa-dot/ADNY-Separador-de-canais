from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SkillContext:
    project_id: str | None
    active_document_id: str | None
    selected_files: list[str] = field(default_factory=list)
    ui_state: dict[str, Any] = field(default_factory=dict)
    user_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
