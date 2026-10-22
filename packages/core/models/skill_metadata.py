from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SkillStatus(str, Enum):
    IMPLEMENTED = "implemented"
    PARTIAL = "partial"
    STUB = "stub"


@dataclass(slots=True)
class SkillMetadata:
    id: str
    display_name: str
    category: str
    description: str
    input_types: list[str]
    output_types: list[str]
    params_schema: dict[str, Any]
    preconditions: list[str] = field(default_factory=list)
    can_preview: bool = True
    can_undo: bool = True
    status: SkillStatus = SkillStatus.STUB

    def to_catalog_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "category": self.category,
            "description": self.description,
            "input_types": self.input_types,
            "output_types": self.output_types,
            "params_schema": self.params_schema,
            "preconditions": self.preconditions,
            "can_preview": self.can_preview,
            "can_undo": self.can_undo,
            "status": self.status.value,
        }
