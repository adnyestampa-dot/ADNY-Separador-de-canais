from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from packages.core.models.skill_context import SkillContext
from packages.core.models.skill_metadata import SkillMetadata, SkillStatus
from packages.core.models.skill_result import SkillResult


class SkillExecutor(Protocol):
    skill_id: str
    display_name: str
    metadata: SkillMetadata

    def execute(self, context: SkillContext, params: dict[str, Any]) -> SkillResult:
        ...


class BaseSkill(ABC):
    """Base class for all skills with metadata and execution contract."""

    skill_id: str = ""
    display_name: str = ""
    category: str = "general"
    description: str = ""
    input_types: list[str] = ["image"]
    output_types: list[str] = ["image"]
    params_schema: dict[str, Any] = {}
    preconditions: list[str] = []
    can_preview: bool = True
    can_undo: bool = True
    status: SkillStatus = SkillStatus.STUB

    @property
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            id=self.skill_id,
            display_name=self.display_name,
            category=self.category,
            description=self.description,
            input_types=self.input_types,
            output_types=self.output_types,
            params_schema=self.params_schema,
            preconditions=self.preconditions,
            can_preview=self.can_preview,
            can_undo=self.can_undo,
            status=self.status,
        )

    @abstractmethod
    def execute(self, context: SkillContext, params: dict[str, Any]) -> SkillResult:
        ...
