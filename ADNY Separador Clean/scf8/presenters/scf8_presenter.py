"""Presenter da versão Clean — só Abrir, Salvar e operações da barra de canais."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox

from apps.desktop_qt.presenters.main_presenter import MainPresenter
from packages.core.models.channel_info import ChannelInfo
from packages.core.models.preview_display import PreviewDisplayMode
from packages.core.services.channel_ops import clone_channel, restore_channel_from_clone
from scf8.branding import APP_NAME, GENERATED_VIEW_TITLE, ORIGINAL_VIEW_TITLE
from scf8.catalog.ss4_actions import ActionStatus, Ss4Action
from scf8.core import separation_ops as ops
from scf8.core.naming import separation_display_name, separation_psd_name
from scf8.core.psd_save_tuning import (
    APPLY_DIVISION_ON_PSD_SAVE,
    is_psd_division_target,
    photoshop_apply_image_divide_self,
)
from scf8.core.separation_undo import ReplaceSeparationsCommand
from scf8.core.ss4_separation_preset import spot_process_ss4_params
from scf8.ui.document_area import ORIGINAL_VIEW, PROOF_VIEW, separation_plate
from scf8.ui.saturation_range_dialog import SaturationRangeDialog

logger = logging.getLogger(__name__)

IN_DEVELOPMENT = "em desenvolvimento"
DEFAULT_UNDO_LIMIT = 10


class Scf8Presenter:
    """Interface enxuta → Abrir (separação FAV8+) / Salvar / barra de canais."""

    def __init__(self, view: Any) -> None:
        self._view = view
        self._core = MainPresenter(view)
        self._densitometer_enabled = True
        self._channel_print: dict[str, bool] = {}
        self._inactive_ids: set[str] = set()
        self._save_path: str | None = None
        self._ink_snapshot: dict | None = None
        self._core.undo_service.set_undo_limit(DEFAULT_UNDO_LIMIT)

    @property
    def project_state(self):
        return self._core.project_state

    @property
    def channels(self):
        return self._core.channels

    def _ss4_params(self) -> dict:
        if self._ink_snapshot is None:
            self._ink_snapshot = self._core._ink_library.load().to_dict()
        return spot_process_ss4_params(
            textile_dark=True,
            ink_library_snapshot=self._ink_snapshot,
        )

    def _sync_view(self) -> None:
        sync = getattr(self._view, "sync_separations_ui", None)
        if callable(sync):
            sync()

    def dispatch(self, action: Ss4Action) -> None:
        if action.status in (ActionStatus.STUB, ActionStatus.PLANNED):
            QMessageBox.information(self._view, action.label, f"{action.label} — {IN_DEVELOPMENT}.")
            return
        if not action.handler:
            QMessageBox.warning(self._view, APP_NAME, f"Sem handler: {action.action_id}")
            return
        handler = getattr(self, action.handler, None) or getattr(self._core, action.handler, None)
        if handler is None:
            QMessageBox.warning(self._view, APP_NAME, f"Handler ausente: {action.handler}")
            return
        handler()

    # ------------------------------------------------------------ Arquivo
    def open_file(self) -> None:
        from packages.image.io import OPEN_FILE_FILTER

        path, _ = QFileDialog.getOpenFileName(self._view, "Abrir", "", OPEN_FILE_FILTER)
        if not path:
            return
        self._view.set_log_message("Carregando…")
        self._core.open_image(path)
        doc = self.project_state.active_document
        if doc is None or not doc.path or Path(doc.path).resolve() != Path(path).resolve():
            self._view.set_log_message("Falha ao abrir.")
            return
        self._save_path = None
        self._inactive_ids.clear()
        self._channel_print.clear()
        self._sync_view()
        self._view.set_log_message("Separação Spot Process (FAV8+) — a interface continua responsiva…")
        QTimer.singleShot(80, self.run_separation)

    def run_separation(self) -> None:
        self._core.separate_channels(self._ss4_params(), prompt_engine=False)

    def document_name(self) -> str | None:
        doc = self.project_state.active_document
        if doc is None:
            return None
        return Path(doc.path).name if doc.path else "Sem título"

    def document_title(self) -> str | None:
        if self.project_state.active_document is None:
            return None
        return GENERATED_VIEW_TITLE

    def render_document_view(self, kind: str) -> tuple[str, Any] | None:
        state = self.project_state
        doc = state.active_document
        if doc is None:
            return None
        if kind == ORIGINAL_VIEW:
            image = doc.pil_image
            return (ORIGINAL_VIEW_TITLE, image) if image is not None else None
        if kind == PROOF_VIEW:
            image = self._view.canvas.display_image()
            return (GENERATED_VIEW_TITLE, image) if image is not None else None
        channel = next((ch for ch in state.channels if ch.id == kind), None)
        if channel is None or channel.mask is None:
            return None
        film = state.preview_display_mode == PreviewDisplayMode.FILM
        plate = separation_plate(channel.mask, None if film else channel.color_rgb)
        return self._channel_label(channel), plate

    def has_open_work(self) -> bool:
        state = self.project_state
        return state.active_document is not None or bool(state.channels)

    def prompt_save_before_quit(self) -> bool:
        if not self.has_open_work():
            return True
        box = QMessageBox(self._view)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(APP_NAME)
        box.setText("Há um trabalho aberto. Deseja salvar antes de sair?")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        yes = box.button(QMessageBox.StandardButton.Yes)
        no = box.button(QMessageBox.StandardButton.No)
        if yes is not None:
            yes.setText("Sim")
        if no is not None:
            no.setText("Não")
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        if box.exec() == QMessageBox.StandardButton.Yes:
            return self.save_document()
        return True

    def close_document(self) -> None:
        self._core.restore_state({})
        self._view.channels_dock.set_channels([])
        self._view.canvas.set_original_from_pil(None)
        self._view.canvas.set_result_from_pil(None)
        self._channel_print.clear()
        self._inactive_ids.clear()
        self._save_path = None
        self._view.update_status_bar()
        self._sync_view()
        self._view.set_log_message("Documento fechado.")

    def save_document(self) -> bool:
        if not self.project_state.channels:
            QMessageBox.warning(self._view, "Salvar", "Abra uma arte primeiro.")
            return False
        if self._save_path:
            return self._write_psd(self._save_path)
        return self.save_document_as()

    def save_document_as(self) -> bool:
        state = self.project_state
        if not state.channels:
            QMessageBox.warning(self._view, "Salvar como", "Abra uma arte primeiro.")
            return False
        doc = state.active_document
        source = Path(doc.path) if doc is not None and doc.path else None
        suggested = self._save_path or (
            str(source.with_name(f"{source.stem}_separations.psd")) if source else "separations.psd"
        )
        path, _ = QFileDialog.getSaveFileName(self._view, "Salvar como", suggested, "Photoshop (*.psd)")
        if not path:
            return False
        if not path.lower().endswith(".psd"):
            path += ".psd"
        if self._write_psd(path):
            self._save_path = path
            return True
        return False

    def _psd_export_channels(self, channels: list[ChannelInfo]) -> list[ChannelInfo]:
        """Canais do PSD: CAMISETA PRETA (RGB 0,0,0) antes da base + nomes em português."""
        visible = [ch for ch in channels if ch.visible and ch.mask is not None]
        if not visible:
            return []
        h, w = visible[0].mask.shape[:2]
        camiseta = ChannelInfo.create(
            "CAMISETA PRETA",
            (0, 0, 0),
            np.ones((h, w), dtype=np.float32),
            channel_id="camiseta-preta-export",
            key="camiseta_preta",
            export_name="CAMISETA PRETA",
            role="spot_black",
        )
        prepared: list[ChannelInfo] = [camiseta]
        division_labels: list[str] = []
        for ch in visible:
            exported = clone_channel(ch)
            label = separation_psd_name(ch.name) or ch.name
            if APPLY_DIVISION_ON_PSD_SAVE and is_psd_division_target(
                ch.name, role=ch.role or "", key=ch.key or ""
            ):
                assert exported.mask is not None
                exported.set_mask(photoshop_apply_image_divide_self(exported.mask))
                division_labels.append(label)
            exported.name = label
            exported.export_name = label
            prepared.append(exported)
        if division_labels:
            logger.info(
                "PSD: Aplicar Imagem / Divisão 100%% em %s (desligar em scf8/core/psd_save_tuning.py)",
                ", ".join(division_labels),
            )
        return prepared

    def _write_psd(self, path: str) -> bool:
        from packages.image.psd_spot_export import export_spot_psd
        from packages.image.textile import compose_with_ground, ground_color_for_state

        state = self.project_state
        export_channels = self._psd_export_channels(list(state.channels))
        if not export_channels:
            QMessageBox.warning(self._view, "Salvar", "Nenhum canal visível para exportar.")
            return False
        # Composite sem a CAMISETA PRETA (placa sólida) para não escurecer o RGB do PSD.
        ink_plates = export_channels[1:]
        shape = ink_plates[0].mask.shape[:2]
        composite = (
            state.result_document.pil_image
            if state.result_document is not None and state.result_document.pil_image is not None
            else compose_with_ground(ink_plates, shape, ground_color_for_state(state))
        )
        self._view.set_log_message("Salvando PSD…")
        try:
            export_spot_psd(export_channels, path, composite=composite)
        except Exception as exc:
            logger.exception("Falha ao salvar PSD spot")
            self._view.set_log_message("Falha ao salvar PSD.")
            QMessageBox.warning(self._view, "Salvar", str(exc))
            return False
        self._view.set_log_message(f"PSD salvo: {path}")
        return True

    # ------------------------------------------------------------ Barra de canais / undo
    def apply_separations_state(self, order: list[str], snapshots: dict) -> None:
        live = {ch.id: ch for ch in self.project_state.channels}
        channels = []
        for cid in order:
            snap = snapshots.get(cid)
            if snap is not None:
                channels.append(clone_channel(snap))
            elif cid in live:
                channels.append(live[cid])
        self._core.channels.set_channels(channels)
        self._sync_view()

    def _commit_edit(self, title: str, edit: ops.SeparationEdit | None, empty_message: str) -> bool:
        if edit is None or edit.is_noop:
            QMessageBox.information(self._view, title, empty_message)
            return False
        before = list(self.project_state.channels)
        self._core.undo_service.push(ReplaceSeparationsCommand(title, before, edit, self))
        self._view.set_log_message(edit.message or title)
        return True

    def schedule_underbase_sync(self) -> None:
        """Sem base branca dinâmica nesta versão — no-op (slot da barra de canais)."""
        return

    def set_separation_visible(self, channel_id: str, visible: bool) -> None:
        self._core.set_channel_visible(channel_id, visible)
        self._view.channels_dock.set_channel_checked(channel_id, visible)

    def set_channel_visible(self, channel_id: str, visible: bool) -> None:
        self.set_separation_visible(channel_id, visible)

    def set_channel_opacity(self, channel_id: str, opacity: float) -> None:
        self._core.set_channel_opacity(channel_id, opacity)

    def reorder_channels(self, order: list[str]) -> None:
        self._core.reorder_channels(order)

    def merge_channels(self, source_id: str, target_id: str) -> None:
        self._core.merge_channels(source_id, target_id)

    def change_channel_color(self, channel_id: str) -> None:
        self._core.change_channel_color(channel_id)

    def delete_channel(self, channel_id: str) -> None:
        self._core.delete_channel(channel_id)

    def isolate_key_channel(self, channel_id: str) -> None:
        self._core.isolate_key_channel(channel_id)

    def document_properties(self, channel_id: str | None = None) -> None:
        state = self.project_state
        doc = state.active_document
        if doc is None:
            QMessageBox.information(self._view, "Propriedades do documento", "Nenhum documento aberto.")
            return
        names = ", ".join(separation_display_name(ch.name) for ch in state.channels) or "—"
        tecido = (
            f"RGB personalizado {state.ground_rgb_override}"
            if state.ground_rgb_override
            else state.textile_preset.value
        )
        text = (
            f"Arquivo: {doc.path or 'Sem título'}\n"
            f"Tamanho: {doc.width} × {doc.height} px\n"
            f"Resolução: {doc.dpi[0]:.0f} dpi\n"
            f"Tamanho de impressão: {doc.width / max(doc.dpi[0], 1):.2f} × "
            f"{doc.height / max(doc.dpi[1], 1):.2f} pol\n"
            f"Tecido: {tecido}\n"
            f"Separações ({len(state.channels)}): {names}"
        )
        channel = next((ch for ch in state.channels if ch.id == channel_id), None)
        if channel is not None:
            text += (
                f"\n\nSeparação: {self._channel_label(channel)}\n"
                f"Cor: RGB {tuple(channel.color_rgb)}\n"
                f"Cobertura: {ops.coverage(channel):.1%}"
            )
        QMessageBox.information(self._view, "Propriedades do documento", text)

    def open_in_new_window(self, kind: str = PROOF_VIEW) -> None:
        if self.project_state.active_document is None:
            QMessageBox.warning(self._view, "Nova janela", "Abra uma arte primeiro.")
            return
        window = self._view.documents.open_window(kind)
        if window is None:
            QMessageBox.information(self._view, "Nova janela", "Ainda não há nada para mostrar em nova janela.")
            return
        self._view.set_log_message(f"Nova janela: {window.windowTitle()}")

    def open_selected_in_new_window(self) -> None:
        channel = self._target_channel("Abrir em nova janela")
        if channel is not None:
            self.open_in_new_window(channel.id)

    def select_channel(self, channel_id: str | None) -> bool:
        return self._view.channels_dock.select_channel(channel_id)

    def selected_channel_id(self) -> str | None:
        return self._view.channels_dock.selected_channel_id()

    @staticmethod
    def _channel_label(channel) -> str:
        return separation_display_name(channel.name) or channel.id[:8]

    def _target_channel(self, title: str):
        channels = self.project_state.channels
        if not channels:
            QMessageBox.warning(self._view, title, "Abra uma arte primeiro.")
            return None
        selected = self.selected_channel_id()
        channel = next((ch for ch in channels if ch.id == selected), None)
        if channel is not None:
            return channel
        names = [self._channel_label(ch) for ch in channels]
        if len(set(names)) != len(names):
            names = [f"{name} ({ch.id[:8]})" for name, ch in zip(names, channels)]
        choice, ok = QInputDialog.getItem(self._view, title, "Separação:", names, 0, False)
        if not ok or choice not in names:
            return None
        channel = channels[names.index(choice)]
        self.select_channel(channel.id)
        return channel

    def delete_selected_channel(self) -> None:
        channel = self._target_channel("Excluir separação")
        if channel is not None:
            self._core.delete_channel(channel.id)

    def duplicate_selected_channel(self) -> None:
        channel = self._target_channel("Duplicar separação")
        if channel is not None:
            self._core.channels.duplicate_channel(channel.id)

    def adjust_selected_channel(self) -> None:
        channel = self._target_channel("Ajustar separação")
        if channel is not None:
            self._adjust_channel_saturation(channel)

    def adjust_separation(self, channel_id: str) -> None:
        channel = next((ch for ch in self.project_state.channels if ch.id == channel_id), None)
        if channel is not None:
            self._adjust_channel_saturation(channel)

    def _adjust_channel_saturation(self, channel: ChannelInfo) -> None:
        if channel.mask is None:
            QMessageBox.warning(
                self._view, "Ajustar separação", f'"{channel.name}" não tem dados para ajustar.'
            )
            return
        self._adjust_saturation_range("Ajustar separação", [channel.id], self._channel_label(channel))

    def _adjust_saturation_range(self, title: str, target_ids: list[str], subtitle: str) -> None:
        state = self.project_state
        candidates = [ch for ch in state.channels if ch.mask is not None]
        checked = {cid for cid in target_ids if any(ch.id == cid for ch in candidates)}
        if not checked:
            QMessageBox.information(self._view, title, "Nenhuma separação ativa para ajustar.")
            return
        originals = {ch.id: clone_channel(ch) for ch in candidates}
        dialog = SaturationRangeDialog(
            self._view,
            subtitle=subtitle,
            separations=[(ch.id, tuple(ch.color_rgb), self._channel_label(ch)) for ch in candidates],
            checked_ids=checked,
        )

        def preview(high: int, low: int) -> None:
            ids = set(dialog.checked_ids() or ())
            for ch in candidates:
                source = ops.source_mask(originals[ch.id])
                ch.set_mask(ops.saturation_range(source, high, low) if ch.id in ids else source)
            self._core.channels.refresh_preview(incremental=True)

        dialog.range_changed.connect(preview)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        dialog.range_changed.disconnect(preview)
        for ch in candidates:
            restore_channel_from_clone(ch, originals[ch.id])
        ids = dialog.checked_ids() or []
        if not accepted or dialog.is_identity() or not ids:
            self._core.channels.refresh_preview(incremental=False)
            return
        edit = ops.adjust_saturation_range(state.channels, ids, dialog.high(), dialog.low())
        self._commit_edit(title, edit, "Nada para ajustar.")

    def on_result_pixel_probe(self, x: int, y: int) -> None:
        if self._densitometer_enabled:
            self._core.on_result_pixel_probe(x, y)

    def set_channel_print_enabled(self, channel_id: str, enabled: bool) -> None:
        self._channel_print[channel_id] = bool(enabled)
        self._view.set_log_message(f"Impressão {'ligada' if enabled else 'desligada'}: {channel_id[:8]}")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._core, name)
