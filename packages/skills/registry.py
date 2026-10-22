from __future__ import annotations

from typing import Any

from packages.core.models.skill_metadata import SkillMetadata
from packages.skills.base import BaseSkill
from packages.skills.separate_channels.skill import SeparateChannelsSkill


class SkillRegistry:
    """Central registry for all available skills."""

    _instance: SkillRegistry | None = None

    def __init__(self) -> None:
        self._skills: dict[str, BaseSkill] = {}
        self._register_defaults()

    @classmethod
    def instance(cls) -> SkillRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def _register_defaults(self) -> None:
        self.register(SeparateChannelsSkill())

    def register(self, skill: BaseSkill) -> None:
        self._skills[skill.skill_id] = skill

    def get(self, skill_id: str) -> BaseSkill | None:
        return self._skills.get(skill_id)

    def list_skills(self) -> list[BaseSkill]:
        return list(self._skills.values())

    def list_metadata(self) -> list[SkillMetadata]:
        return [s.metadata for s in self._skills.values()]

    def to_catalog_dict(self) -> list[dict[str, Any]]:
        return [s.metadata.to_catalog_dict() for s in self._skills.values()]

    def skill_ids(self) -> list[str]:
        return list(self._skills.keys())
