from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QMessageBox

from packages.core.jobs.job_manager import JobManager
from packages.core.models.project_state import ProjectState
from packages.core.models.skill_context import SkillContext
from packages.skills.registry import SkillRegistry


class SeparationPresenter:
    """Submete exclusivamente jobs de separação FAV8+."""

    def __init__(self, view: Any, project_state: ProjectState, job_manager: JobManager) -> None:
        self._view = view
        self._state = project_state
        self._jobs = job_manager
        self._skill = SkillRegistry.instance().get("separate_channels")

    def run(self, params: dict[str, Any]):
        document = self._state.active_document
        if document is None:
            QMessageBox.warning(self._view, "Aviso", "Abra uma imagem primeiro.")
            return None
        if self._jobs.has_running_skill("separate_channels"):
            QMessageBox.information(self._view, "Separar", "Separação em andamento. Aguarde concluir.")
            return None
        params = {**params, "engine": "fav8_plus"}
        self._state.separation_params = params
        self._state.separation_document = document
        self._view.canvas.set_original_from_pil(document.pil_image)
        self._view.canvas.set_left_panel_title("Original")
        separation_document = self._state.document_for_separation()

        def execute():
            context = SkillContext(
                project_id=None,
                active_document_id=separation_document.id if separation_document else None,
                metadata={
                    "image_array": separation_document.array if separation_document else None,
                    "pil_image": separation_document.pil_image if separation_document else None,
                },
            )
            if self._skill is None:
                raise RuntimeError("Skill separate_channels não registrada.")
            return self._skill.execute(context, params)

        return self._jobs.submit("separate_channels", execute)
