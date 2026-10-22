from __future__ import annotations

import copy
import logging
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from apps.desktop_qt.canvases.image_view import CanvasTool
from apps.desktop_qt.dialogs.prepress_dialog import PrepressDialog
from apps.desktop_qt.dialogs.ink_library_dialog import InkLibraryDialog
from apps.desktop_qt.dialogs.separation_dialog import ask_separation_params
from apps.desktop_qt.presenters.channels_presenter import ChannelsPresenter
from apps.desktop_qt.presenters.separation_presenter import SeparationPresenter
from packages.core.events.event_bus import get_event_bus
from packages.core.jobs.job_manager import JobManager
from packages.core.models.preview_display import PreviewDisplayMode
from packages.core.models.project_state import ProjectState, TextilePreset
from packages.core.models.skill_result import SkillResult
from packages.core.services.audit_service import AuditService
from packages.core.services.export_service import ExportService
from packages.core.services.ink_library_service import InkLibraryService
from packages.core.undo.undo_stack import LoadImageCommand, UndoStackService
from packages.image.io import load_image
from packages.image.textile import ground_color_for_state
from packages.infra.sqlite.database import Database

logger = logging.getLogger(__name__)


class MainPresenter:
    """Orchestrates core operations — delegates to specialized presenters."""

    def __init__(self, view: Any) -> None:
        self._view = view
        self.project_state = ProjectState()
        self._job_manager = JobManager()
        self._export_service = ExportService()
        self._ink_library = InkLibraryService()
        self._undo = UndoStackService()
        self._db = Database()
        self._audit = AuditService.instance()
        self._last_separation_params: dict[str, Any] = {}
        self._events = get_event_bus()
        self._job_params: dict[str, dict] = {}

        self.separation = SeparationPresenter(view, self.project_state, self._job_manager)
        self.channels = ChannelsPresenter(view, self.project_state, self._undo, audit=self._audit)
        self._connect_job_signals()
        self._wire_event_bus()

    def _wire_event_bus(self) -> None:
        self._events.log_message.connect(self._on_bus_log)

    def _on_bus_log(self, message: str) -> None:
        logger.info("ui: %s", message)
        self._audit.record("ui_log", {"message": message[:500]})

    def _connect_job_signals(self) -> None:
        self._job_manager.job_started.connect(self._on_job_started)
        self._job_manager.job_finished.connect(self._on_job_finished)
        self._job_manager.job_failed.connect(self._on_job_failed)

    @property
    def undo_service(self) -> UndoStackService:
        return self._undo

    def _submit_export_psd_job(self, params: dict):
        path = params.get("path")
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self._view, "Exportar PSD", "separacao.psd", "PSD (*.psd)"
            )
            if not path:
                raise RuntimeError("Export PSD cancelado pelo operador.")

        def run():
            composite = None
            if self.project_state.result_document:
                composite = self.project_state.result_document.pil_image
            ok, messages, warnings = self._export_service.export_psd(
                self.project_state.channels,
                path,
                composite=composite,
                ground_rgb=ground_color_for_state(self.project_state),
            )
            return SkillResult(ok=ok, messages=messages, warnings=warnings, artifacts={"path": path})

        return self._job_manager.submit("export_psd", run)

    def _submit_export_png_job(self, params: dict):
        path = params.get("path")
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self._view, "Exportar PNG", "resultado.png", "PNG (*.png)"
            )
            if not path:
                raise RuntimeError("Export PNG cancelado pelo operador.")
        doc = self.project_state.result_document or self.project_state.active_document

        def run():
            if doc is None:
                return SkillResult(ok=False, messages=["Nenhum documento para exportar."])
            image = doc.pil_image
            if self.project_state.channels:
                image = self._export_service.compose_edited_visible(
                    self.project_state.channels,
                    (doc.height, doc.width),
                    ground_color_for_state(self.project_state),
                )
            msgs = self._export_service.export_png(image, path, dpi=(300.0, 300.0))
            return SkillResult(ok=True, messages=msgs, artifacts={"path": path})

        return self._job_manager.submit("export_png", run)

    def open_image_dialog(self) -> None:
        from packages.image.io import OPEN_FILE_FILTER

        path, _ = QFileDialog.getOpenFileName(
            self._view,
            "Abrir imagem",
            "",
            OPEN_FILE_FILTER,
        )
        if path:
            self.open_image(path)

    def open_image(self, path: str) -> None:
        try:
            old_state = self._snapshot_state()
            doc = load_image(path)
            self.project_state.active_document = doc
            self.project_state.channels = []
            self.project_state.result_document = None
            self.project_state.separation_document = None
            self.project_state.separation_manifest = {}
            self.project_state.separation_diagnostics = {}
            self._view.canvas.set_original_from_pil(doc.pil_image)
            self._view.canvas.set_left_panel_title("Original")
            self._view.canvas.set_result_from_pil(None)
            self._view.channels_dock.set_channels([])
            self._view.update_status_bar()
            self._undo.push(LoadImageCommand(self, path, old_state))
            payload = {
                "path": path,
                "width": doc.width,
                "height": doc.height,
                "dpi": doc.dpi,
            }
            self._audit.record("image_opened", payload)
            self._events.image_opened.emit(path)
            logger.info("Imagem aberta: %s", path)
        except Exception as exc:
            logger.exception("Erro ao abrir imagem")
            QMessageBox.critical(self._view, "Erro", f"Não foi possível abrir a imagem:\n{exc}")

    def load_image_direct(self, path: str) -> None:
        doc = load_image(path)
        self.project_state.active_document = doc
        self.project_state.channels = []
        self._view.canvas.set_original_from_pil(doc.pil_image)
        self._view.update_status_bar()

    def _snapshot_state(self) -> dict:
        doc = self.project_state.active_document
        return {"path": doc.path if doc else None}

    def restore_state(self, state: dict | None) -> None:
        if state and state.get("path"):
            self.load_image_direct(state["path"])
        else:
            self.project_state.active_document = None
            self.project_state.channels = []
            self._view.canvas.set_original_from_pil(None)
            self._view.update_status_bar()

    def separate_channels(self, params: dict | None = None, *, prompt_engine: bool = True) -> None:
        if isinstance(params, bool):
            params = None
        if self.project_state.active_document is None:
            QMessageBox.warning(self._view, "Aviso", "Abra uma imagem primeiro.")
            return
        if self._job_manager.has_running_skill("separate_channels"):
            QMessageBox.information(
                self._view,
                "Separar",
                "Separação em andamento. Aguarde concluir — imagens grandes podem levar alguns minutos.",
            )
            return
        if params is None and prompt_engine:
            chosen = ask_separation_params(self._view, self._view.params_dock)
            if chosen is None:
                return
            params = {**self._view.params_dock.get_separation_params(), **chosen}
        elif params is None:
            params = {**self._view.params_dock.get_separation_params()}
        params["engine"] = "fav8_plus"
        params["ink_library_snapshot"] = self._ink_library.load().to_dict()
        doc = self.project_state.active_document
        mp = doc.width * doc.height if doc else 0
        hint = ""
        if mp > 4_000_000:
            hint = " Imagem grande — pode levar 1–3 minutos."
        self._view.set_separation_busy(True, f"Separando canais...{hint}")
        job_info = self.separation.run(params)
        if job_info and params:
            # active_document no submit — não o separation_document antigo
            src = self.project_state.active_document
            self._job_params[job_info.job_id] = {
                **params,
                "_source_document_id": src.id if src else None,
            }

    def _on_job_started(self, job_info) -> None:
        if job_info:
            self._events.skill_started.emit(job_info.skill_id, job_info.job_id)
            params = self._job_params.get(job_info.job_id) or (
                self.project_state.separation_params
                if job_info.skill_id == "separate_channels"
                else {}
            )
            self._audit.record(
                "skill_started",
                {"skill_id": job_info.skill_id, "params": params},
                job_id=job_info.job_id,
            )
            self._db.log_job(
                job_info.job_id,
                job_info.skill_id,
                "running",
                params=params,
            )
        self._view.set_progress(job_info.progress if job_info else 0, f"Executando {job_info.skill_id}...")
        if job_info and job_info.skill_id == "separate_channels":
            self._view.set_separation_busy(True, "Separando canais... aguarde.")

    def _on_job_finished(self, job_info, result) -> None:
        # Protege o app: exceção aqui (UI pós-motor) matava o processo com pythonw.
        try:
            self._on_job_finished_impl(job_info, result)
        except Exception:
            logger.exception("Falha ao aplicar resultado do job na UI")
            try:
                if job_info and job_info.skill_id == "separate_channels":
                    self._view.set_separation_busy(False)
                self._view.set_log_message("Erro ao mostrar a separação (veja o log).")
                QMessageBox.critical(
                    self._view,
                    "Erro",
                    "A separação terminou, mas a interface falhou ao mostrar o resultado.\n"
                    "O app permanece aberto — tente Save ou abra de novo a imagem.",
                )
            except Exception:
                logger.exception("Falha secundária ao reportar erro de UI")

    def _on_job_finished_impl(self, job_info, result) -> None:
        if job_info and job_info.skill_id == "separate_channels":
            self._view.set_separation_busy(False)
        self._view.set_progress(100, "Concluído")
        params: dict = {}
        if job_info:
            params = self._job_params.pop(job_info.job_id, {})
            manifest = result.artifacts.get("separation_manifest_json")
            diagnostics = result.artifacts.get("separation_diagnostics_json")
            persisted_result = {"ok": result.ok, "messages": result.messages}
            if manifest is not None:
                persisted_result["separation_manifest"] = manifest
            if diagnostics is not None:
                persisted_result["separation_diagnostics"] = diagnostics
            self._db.log_job(
                job_info.job_id,
                job_info.skill_id,
                "completed",
                params=params,
                result=persisted_result,
                finished_at=job_info.finished_at.isoformat() if job_info.finished_at else None,
            )
            self._events.skill_finished.emit(job_info.skill_id, result.ok)
            self._audit.record(
                "skill_finished",
                {
                    "skill_id": job_info.skill_id,
                    "ok": result.ok,
                    "messages": result.messages,
                    "params": params,
                        "separation_manifest": manifest,
                        "separation_diagnostics": diagnostics,
                },
                job_id=job_info.job_id,
            )
            if job_info.skill_id == "separate_channels" and result.ok:
                self._last_separation_params = {
                    key: value
                    for key, value in params.items()
                    if key != "_source_document_id"
                }
        applied = self._apply_skill_result(job_info, result, params)
        if (
            applied
            and job_info
            and job_info.skill_id == "separate_channels"
            and result.ok
        ):
            manifest = result.artifacts.get("separation_manifest_json")
            diagnostics = result.artifacts.get("separation_diagnostics_json")
            self._audit.record(
                "separation_completed",
                {
                    "params": params,
                    "channel_count": len(result.artifacts.get("channels", [])),
                    "engine": result.artifacts.get("separation_engine"),
                    "manifest": manifest,
                    "diagnostics": diagnostics,
                },
                job_id=job_info.job_id,
            )
            self._events.separation_completed.emit(
                len(result.artifacts.get("channels", []))
            )

    def _apply_skill_result(self, job_info, result, params: dict | None = None) -> bool:
        if not result.ok:
            if job_info is None or job_info.skill_id not in ("export_psd", "export_png"):
                QMessageBox.warning(self._view, "Skill", "\n".join(result.messages))
            return False
        for w in result.warnings:
            logger.warning(w)

        if "channels" in result.artifacts:
            if job_info and job_info.skill_id == "separate_channels":
                if not self._separation_result_matches_document(
                    result.artifacts["channels"],
                    (params or {}).get("_source_document_id"),
                ):
                    return False
            channels = result.artifacts["channels"]
            result_image = result.artifacts.get("result_image")
            if result_image:
                self.project_state.result_document = copy.copy(self.project_state.active_document)
            # Primeiro monta a barra de canais; o preview completo no próximo tick
            # (evita crash Qt 6.11 ao reconstruir menus + pixmap no mesmo slot do job).
            self.channels.set_channels(channels, refresh=False)
            QTimer.singleShot(0, lambda: self.channels.refresh_preview(incremental=False))
            if job_info and job_info.skill_id == "separate_channels":
                params = self._last_separation_params or self.project_state.separation_params or {}
                engine = result.artifacts.get("separation_engine")
                if engine:
                    self.project_state.separation_params = {
                        **self.project_state.separation_params,
                        **params,
                        "engine": engine,
                    }
                self.project_state.separation_manifest = dict(
                    result.artifacts.get("separation_manifest_json") or {}
                )
                self.project_state.separation_diagnostics = dict(
                    result.artifacts.get("separation_diagnostics_json") or {}
                )
        elif "path" in result.artifacts and job_info and job_info.skill_id == "export_psd":
            self._audit.record("psd_exported", {"path": result.artifacts["path"], "ok": True})
            self._events.psd_exported.emit(result.artifacts["path"], True)
        elif "path" in result.artifacts and job_info and job_info.skill_id == "export_png":
            self._audit.record("png_exported", {"path": result.artifacts["path"]})
            self._events.png_exported.emit(result.artifacts["path"])

        self._view.update_status_bar()
        if result.messages:
            self._view.set_log_message(result.messages[-1])
        return True

    def _separation_result_matches_document(
        self,
        channels: list,
        source_document_id: str | None,
    ) -> bool:
        doc = self.project_state.active_document
        if source_document_id and (doc is None or doc.id != source_document_id):
            logger.warning(
                "Resultado de separação descartado: documento mudou durante o processamento."
            )
            self._view.set_log_message(
                "Separação anterior descartada — a imagem foi trocada durante o processamento."
            )
            return False
        if doc:
            expected = (doc.height, doc.width)
            for channel in channels:
                mask = getattr(channel, "mask", None)
                if mask is not None and mask.shape[:2] != expected:
                    logger.warning(
                        "Resultado de separação descartado: dimensões incompatíveis (%s vs %s).",
                        mask.shape[:2],
                        expected,
                    )
                    self._view.set_log_message(
                        "Separação descartada — dimensões dos canais não correspondem à imagem ativa."
                    )
                    return False
        return True

    def _on_job_failed(self, job_info, error: str) -> None:
        if job_info and job_info.skill_id == "separate_channels":
            self._view.set_separation_busy(False)
        self._view.set_progress(0, "Erro")
        if job_info:
            params = self._job_params.pop(job_info.job_id, {})
            self._db.log_job(
                job_info.job_id,
                job_info.skill_id,
                "failed",
                params=params,
                result={"error": error},
                finished_at=job_info.finished_at.isoformat() if job_info.finished_at else None,
                error=error,
            )
            self._events.skill_finished.emit(job_info.skill_id, False)
            self._audit.record(
                "skill_failed",
                {"skill_id": job_info.skill_id, "error": error, "params": params},
                job_id=job_info.job_id,
            )
        QMessageBox.critical(self._view, "Erro no job", error)

    def set_channel_visible(self, channel_id: str, visible: bool) -> None:
        self.channels.set_channel_visible(channel_id, visible)

    def set_channel_opacity(self, channel_id: str, opacity: float) -> None:
        self.channels.set_channel_opacity(channel_id, opacity)

    def isolate_key_channel(self, channel_id: str, isolated: bool) -> None:
        self.channels.isolate_key_channel(channel_id, isolated)

    def reorder_channels(self, ordered_ids: list[str]) -> None:
        self.channels.reorder_channels(ordered_ids)

    def merge_channels(self, source_id: str, target_id: str) -> None:
        self.channels.merge_channels(source_id, target_id)

    def change_channel_color(self, channel_id: str) -> None:
        self.channels.change_channel_color(channel_id)

    def delete_channel(self, channel_id: str) -> None:
        self.channels.delete_channel(channel_id)

    def adjust_channel(self, channel_id: str) -> None:
        self.channels.adjust_channel(channel_id)

    def set_textile_preset(self, preset_name: str) -> None:
        try:
            self.project_state.textile_preset = TextilePreset(preset_name)
            self.project_state.ground_rgb_override = None
            self._view.textiles_dock.set_active_preset(preset_name)
            self.channels.refresh_preview()
            self._audit.record("textile_preset_changed", {"preset": preset_name})
            self._events.textile_preset_changed.emit(preset_name)
        except ValueError:
            pass

    def set_custom_ground_color(self, rgb: tuple[int, int, int]) -> None:
        r, g, b = (int(max(0, min(255, c))) for c in rgb)
        self.project_state.ground_rgb_override = (r, g, b)
        self._view.textiles_dock.set_active_preset("")
        self.channels.refresh_preview()
        self._audit.record("ground_color_changed", {"rgb": [r, g, b]})

    def handle_tool(self, tool_id: str) -> None:
        if tool_id == "zoom_in":
            self._view.canvas.zoom_in()
        elif tool_id == "zoom_out":
            self._view.canvas.zoom_out()
        elif tool_id == "move":
            self._view.canvas.set_tool(CanvasTool.MOVE)
        elif tool_id == "zoom":
            self._view.canvas.set_tool(CanvasTool.ZOOM)

    def export_png(self) -> None:
        doc = self.project_state.result_document or self.project_state.active_document
        if doc is None:
            QMessageBox.warning(self._view, "Aviso", "Nada para exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self._view, "Exportar PNG", "resultado.png", "PNG (*.png)"
        )
        if path:
            image = doc.pil_image
            if self.project_state.channels:
                image = self._export_service.compose_edited_visible(
                    self.project_state.channels,
                    (doc.height, doc.width),
                    ground_color_for_state(self.project_state),
                )
            msgs = self._export_service.export_png(image, path, dpi=(300.0, 300.0))
            self._audit.record("png_exported", {"path": path})
            self._events.png_exported.emit(path)
            self._view.set_log_message(msgs[0])

    def export_channels(self) -> None:
        if not self.project_state.channels:
            QMessageBox.warning(self._view, "Aviso", "Execute a separação primeiro.")
            return
        output_dir = QFileDialog.getExistingDirectory(self._view, "Pasta para canais")
        if output_dir:
            msgs = self._export_service.export_channels_as_pngs(
                self.project_state.channels, output_dir
            )
            self._audit.record("png_exported", {"paths": msgs, "type": "channels"})
            self._view.set_log_message(f"{len(msgs)} canal(is) exportado(s).")

    def export_psd(self) -> None:
        if not self.project_state.channels:
            QMessageBox.warning(self._view, "Aviso", "Execute a separação primeiro.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self._view, "Exportar PSD", "separacao.psd", "PSD (*.psd)"
        )
        if path:
            composite = None
            if self.project_state.result_document:
                composite = self.project_state.result_document.pil_image
            ok, messages, warnings = self._export_service.export_psd(
                self.project_state.channels,
                path,
                composite=composite,
                ground_rgb=ground_color_for_state(self.project_state),
            )
            self._audit.record("psd_exported", {"path": path, "ok": ok, "warnings": warnings})
            self._events.psd_exported.emit(path, ok)
            QMessageBox.information(self._view, "Exportar PSD", "\n".join(messages + warnings))

    def export_films_pdf(self) -> None:
        if not self.project_state.channels:
            QMessageBox.warning(self._view, "Aviso", "Execute a separação primeiro.")
            return
        document = self.project_state.active_document
        source_dpi = document.dpi[0] if document else 300.0
        dialog = PrepressDialog(
            self._view,
            dpi=source_dpi,
            channels=self.project_state.channels,
            initial_config=self.project_state.prepress_config,
            alpha=document.alpha if document else None,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        config = dialog.config()
        self.project_state.prepress_config = config
        path, _ = QFileDialog.getSaveFileName(
            self._view, "Exportar filmes PDF", "filmes.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        metadata = {
            **self.project_state.separation_manifest,
            "diagnostics": self.project_state.separation_diagnostics,
        }
        ok, messages, warnings = self._export_service.export_films_pdf(
            self.project_state.channels,
            path,
            config,
            alpha=document.alpha if document else None,
            metadata=metadata,
        )
        self._audit.record(
            "films_pdf_exported",
            {"path": path, "ok": ok, "warnings": warnings, "dpi": config.film.dpi},
        )
        icon = QMessageBox.Icon.Information if ok else QMessageBox.Icon.Warning
        box = QMessageBox(icon, "Exportar filmes PDF", "\n".join(messages + warnings), parent=self._view)
        box.exec()

    def undo(self) -> None:
        if self._undo.can_undo():
            self._undo.undo()

    def redo(self) -> None:
        if self._undo.can_redo():
            self._undo.redo()

    def show_original_only(self) -> None:
        doc = self.project_state.active_document
        if doc:
            self._view.canvas.set_result_from_pil(doc.pil_image)

    def edit_ink_library(self) -> None:
        dialog = InkLibraryDialog(self._view, self._ink_library)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._view.set_log_message(
                "Biblioteca de tintas salva; será aplicada na próxima separação."
            )

    def on_preview_display_mode_changed(self, mode_value: str) -> None:
        mode = PreviewDisplayMode.from_value(mode_value)
        if self.project_state.preview_display_mode == mode:
            return
        self.project_state.preview_display_mode = mode
        self._view.channels_dock.set_preview_display_mode(mode)
        self.channels.refresh_preview(incremental=False)
        self._view.set_log_message(f"Visualização: {mode.value}")

    def on_result_pixel_probe(self, x: int, y: int) -> None:
        if not self.project_state.channels:
            return
        self._view.set_density_message(self.channels.density_status_at(x, y))

    def open_production_delivery(self) -> None:
        """Fluxo de entrega: pré-impressão + export PDF (paridade Print Window simplificada)."""
        if not self.project_state.channels:
            QMessageBox.information(
                self._view,
                "Entrega",
                "Separe os canais antes de preparar filmes.",
            )
            return
        self.export_films_pdf()

