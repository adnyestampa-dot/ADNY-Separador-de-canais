from __future__ import annotations



import logging
import uuid

from typing import Any



from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from PySide6.QtGui import QColor

from PySide6.QtWidgets import QColorDialog, QDialog, QMessageBox



from apps.desktop_qt.dialogs.channel_adjust_dialog import ChannelAdjustDialog

from packages.core.events.event_bus import get_event_bus

from packages.core.models.preview_display import PreviewDisplayMode
from packages.core.models.project_state import ProjectState

from packages.core.services.audit_service import AuditService

from packages.core.services.channel_ops import (

    clone_channel,

    delete_channel,

    merge_channels,

    reorder_channels,

    restore_channel_from_clone,

    set_channel_color,

)

from packages.core.undo.undo_stack import (
    DeleteChannelCommand,
    InsertChannelCommand,
    MergeChannelsCommand,
    ReorderChannelsCommand,
    SetChannelVisibleCommand,
    SetChannelValueCommand,
    UndoStackService,
)

from packages.image.channel_adjust import ChannelAdjustments, apply_channel_adjustments

from packages.image.separation_preview import channel_density_at, compose_film_preview, format_density_status
from packages.image.textile import (
    compose_with_ground,
    compose_with_ground_fast,
    compose_with_live_mask,
    display_ground_for_state,
)



logger = logging.getLogger(__name__)


class EditAction:
    CHANNEL_VISIBILITY = "channel_visibility"
    CHANNEL_OPACITY = "channel_opacity"
    CHANNEL_ADJUSTED = "channel_adjusted"
    CHANNEL_REORDERED = "channel_reordered"
    CHANNEL_MERGED = "channel_merged"
    CHANNEL_COLOR_CHANGED = "channel_color_changed"
    CHANNEL_DELETED = "channel_deleted"


_PREVIEW_DEBOUNCE_MS = 100





class _PreviewSignals(QObject):
    """Sinais do preview — QObject na thread da UI; emitidos a partir do pool."""

    finished_ok = Signal(int, object)
    finished_err = Signal(int, str)


class _PreviewTask(QRunnable):
    """Uma composição de preview; evita reiniciar QThread (crash Qt 6.11)."""

    def __init__(self, generation: int, fn, signals: _PreviewSignals) -> None:
        super().__init__()
        self._generation = generation
        self._fn = fn
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            image = self._fn()
        except Exception as exc:
            logger.exception("preview render failed")
            try:
                self._signals.finished_err.emit(self._generation, str(exc))
            except RuntimeError:
                pass
            return
        try:
            self._signals.finished_ok.emit(self._generation, image)
        except RuntimeError:
            # App já está fechando — sinal/UI destruídos
            pass


class _PreviewWorker:
    """Preview via QThreadPool — resultados antigos são descartados por generation."""

    def __init__(self) -> None:
        self._signals = _PreviewSignals()
        self.finished_ok = self._signals.finished_ok
        self.finished_err = self._signals.finished_err
        self._pool = QThreadPool.globalInstance()

    def submit(self, generation: int, fn) -> None:
        self._pool.start(_PreviewTask(generation, fn, self._signals))


class ChannelsPresenter:

    """Manages channel visibility, opacity, editing and preview composition."""



    def __init__(

        self,

        view: Any,

        project_state: ProjectState,

        undo: UndoStackService,

        audit: AuditService | None = None,

    ) -> None:

        self._view = view

        self._state = project_state

        self._undo = undo

        self._audit = audit or AuditService.instance()

        self._events = get_event_bus()



        self._preview_timer = QTimer()

        self._preview_timer.setSingleShot(True)

        self._preview_timer.timeout.connect(self._flush_debounced_preview)

        self._pending_live: dict | None = None

        self._preview_worker = _PreviewWorker()

        self._preview_worker.finished_ok.connect(self._on_preview_ready)

        self._preview_worker.finished_err.connect(self._on_preview_error)

        self._preview_generation = 0

        self._interactive_preview = False
        self._isolation_visibility: dict[str, bool] | None = None



    def _track_edit(self, action: EditAction, **kwargs) -> None:
        return



    def _preview_engine(self) -> str:
        return str(self._state.separation_params.get("engine", "fav8_plus"))

    def _dark_fabric(self) -> bool:
        return bool(self._state.separation_params.get("dark_fabric", True))

    def _compose_channel_preview(
        self,
        channels,
        shape: tuple[int, int],
        *,
        visibility: dict[str, bool] | None = None,
        fast: bool = False,
        editing_channel_id: str | None = None,
        live_mask=None,
        live_opacity: float | None = None,
        live_color_rgb: tuple[int, int, int] | None = None,
    ):
        visibility = visibility or self._visibility_snapshot()
        ground = display_ground_for_state(self._state)

        if editing_channel_id is not None and live_mask is not None:
            return compose_with_live_mask(
                channels,
                shape,
                ground,
                editing_channel_id,
                live_mask,
                live_opacity=live_opacity,
                live_color_rgb=live_color_rgb,
                visibility=visibility,
            )
        mode = self._state.preview_display_mode
        if mode == PreviewDisplayMode.FILM:
            return compose_film_preview(channels, shape, visibility=visibility)
        if fast:
            return compose_with_ground_fast(channels, shape, ground, visibility=visibility)
        return compose_with_ground(channels, shape, ground, visibility=visibility)

    def set_preview_display_mode(self, mode: PreviewDisplayMode) -> None:
        self._state.preview_display_mode = mode
        self._view.channels_dock.set_preview_display_mode(mode)
        self.refresh_preview(incremental=False)

    def density_status_at(self, x: int, y: int) -> str:
        visibility = self._visibility_snapshot()
        densities = channel_density_at(
            self._state.channels,
            x,
            y,
            visibility=visibility,
        )
        return format_density_status(densities, x, y)

    def _schedule_preview(self) -> None:

        self._preview_timer.start(_PREVIEW_DEBOUNCE_MS)



    def _next_preview_generation(self) -> int:

        self._preview_generation += 1

        return self._preview_generation



    def _submit_preview(self, fn, *, interactive: bool = False) -> None:

        self._interactive_preview = interactive

        gen = self._next_preview_generation()

        self._preview_worker.submit(gen, fn)



    def _visibility_snapshot(self) -> dict[str, bool]:
        return {ch.id: ch.visible for ch in self._state.channels}

    def _invalidate_preview_worker(self) -> None:
        self._preview_timer.stop()
        self._pending_live = None
        self._next_preview_generation()

    def _on_preview_ready(self, generation: int, image) -> None:
        if generation != self._preview_generation:
            return
        if image is None:
            return
        self._store_result_preview(image)
        if self._view.canvas.has_result_image():
            self._view.canvas.update_result_from_pil(image, fast=self._interactive_preview)
        else:
            self._view.canvas.set_result_from_pil(image)

    def _store_result_preview(self, image) -> None:
        if self._state.result_document is not None:
            self._state.result_document.set_result_image(image)



    def _on_preview_error(self, generation: int, message: str) -> None:

        if generation != self._preview_generation:

            return

        logger.warning("preview error: %s", message)



    def _flush_debounced_preview(self) -> None:

        if self._pending_live:

            pending = self._pending_live

            self._pending_live = None

            self._queue_live_preview(

                pending["channel_id"],

                pending.get("adjustments"),

                opacity=pending.get("opacity"),

                color_rgb=pending.get("color_rgb"),

                opacity_only=bool(pending.get("opacity_only")),

            )

            return

        self.refresh_preview(incremental=True)



    def _queue_live_preview(

        self,

        channel_id: str,

        adj: ChannelAdjustments | None,

        *,

        opacity: float | None = None,

        color_rgb: tuple[int, int, int] | None = None,

        opacity_only: bool = False,

    ) -> None:

        doc = self._state.active_document

        ch = next((c for c in self._state.channels if c.id == channel_id), None)

        if not doc or not ch:

            return



        channels = self._state.channels
        shape = (doc.height, doc.width)
        visibility = self._visibility_snapshot()
        channel_id_copy = channel_id

        opacity_copy = opacity

        color_rgb_copy = color_rgb

        adj_copy = adj.copy() if adj is not None else None



        def _render():

            ch_local = next((c for c in channels if c.id == channel_id_copy), None)

            if ch_local is None:

                return None

            if opacity_only or adj_copy is None:

                if ch_local.mask is None:

                    return None

                live_mask = ch_local.mask

            else:

                if ch_local.raw_mask is None:

                    return None

                live_mask = apply_channel_adjustments(

                    ch_local.raw_mask, adj_copy, fast_preview=True

                )



            return self._compose_channel_preview(
                channels,
                shape,
                visibility=visibility,
                editing_channel_id=channel_id_copy,
                live_mask=live_mask,
                live_opacity=opacity_copy,
                live_color_rgb=color_rgb_copy,
            )



        self._submit_preview(_render, interactive=True)



    def set_channel_visible(self, channel_id: str, visible: bool) -> None:

        for ch in self._state.channels:

            if ch.id == channel_id:

                if ch.visible == visible:

                    return

                old = ch.visible

                self.apply_channel_visible(channel_id, visible, update_ui=False)

                self._track_edit(
                    EditAction.CHANNEL_VISIBILITY,
                    channel_id=channel_id,
                    channel_name=ch.name,
                    before={"visible": old},
                    after={"visible": visible},
                )

                self._undo.push(

                    SetChannelVisibleCommand(channel_id, old, visible, self)

                )

                break

    def isolate_key_channel(self, channel_id: str, isolated: bool) -> None:
        channel = next((item for item in self._state.channels if item.id == channel_id), None)
        if channel is None or channel.role != "key":
            return
        if isolated:
            if self._isolation_visibility is None:
                self._isolation_visibility = self._visibility_snapshot()
            for item in self._state.channels:
                item.visible = item.id == channel_id
                self._view.channels_dock.set_channel_checked(item.id, item.visible)
        else:
            snapshot = self._isolation_visibility or {}
            for item in self._state.channels:
                item.visible = snapshot.get(item.id, True)
                self._view.channels_dock.set_channel_checked(item.id, item.visible)
            self._isolation_visibility = None
        self._invalidate_preview_worker()
        self._refresh_preview_immediate()



    def set_all_channels_visible(self, visible: bool) -> None:
        """Hide/Show All Separations: um único recálculo do composite."""
        self._isolation_visibility = None
        changed = False
        for ch in self._state.channels:
            if ch.visible != visible:
                ch.visible = visible
                changed = True
            self._view.channels_dock.set_channel_checked(ch.id, visible)
        if not changed:
            return
        self._invalidate_preview_worker()
        self._refresh_preview_immediate()

    def apply_channel_visible(

        self, channel_id: str, visible: bool, update_ui: bool = False

    ) -> None:

        for ch in self._state.channels:

            if ch.id == channel_id:

                ch.visible = visible

                if update_ui:

                    self._view.channels_dock.set_channel_checked(channel_id, visible)

                self._invalidate_preview_worker()
                self._refresh_preview_immediate()
                break



    def set_channel_opacity(self, channel_id: str, opacity: float) -> None:
        ch = next((c for c in self._state.channels if c.id == channel_id), None)
        opacity = max(0.0, min(1.0, float(opacity)))
        if ch is None or ch.opacity == opacity:
            return
        old_opacity = ch.opacity
        self._undo.push(
            SetChannelValueCommand(
                "Alterar opacidade",
                "apply_channel_opacity",
                channel_id,
                old_opacity,
                opacity,
                self,
            )
        )
        self._track_edit(
            EditAction.CHANNEL_OPACITY,
            channel_id=channel_id,
            channel_name=ch.name,
            before={"opacity": old_opacity},
            after={"opacity": opacity},
        )

    def apply_channel_opacity(
        self, channel_id: str, opacity: object, update_ui: bool = False
    ) -> None:
        ch = next((c for c in self._state.channels if c.id == channel_id), None)
        if ch is None:
            return
        ch.opacity = max(0.0, min(1.0, float(opacity)))
        if update_ui:
            self._view.channels_dock.update_channel(ch)
        self._invalidate_preview_worker()
        self._refresh_preview_immediate()



    def adjust_channel(self, channel_id: str) -> None:

        ch = next((c for c in self._state.channels if c.id == channel_id), None)

        if ch is None or ch.raw_mask is None:

            return



        original = ch.adjustments.copy()

        dialog = ChannelAdjustDialog(ch.name, ch.adjustments, self._view)



        def _preview_live(adj: ChannelAdjustments) -> None:

            self._pending_live = {"channel_id": channel_id, "adjustments": adj}

            self._schedule_preview()



        dialog.adjustments_changed.connect(_preview_live)

        accepted = dialog.exec() == QDialog.DialogCode.Accepted



        self._preview_timer.stop()

        self._pending_live = None

        self._next_preview_generation()



        if accepted:
            updated_adjustments = dialog.get_adjustments()
            self._undo.push(
                SetChannelValueCommand(
                    "Ajustar máscara",
                    "apply_channel_adjustments",
                    channel_id,
                    original,
                    updated_adjustments.copy(),
                    self,
                )
            )

            payload = {

                "channel_id": ch.id,

                "name": ch.name,

                "adjustments": {

                    "high_saturation": ch.adjustments.high_saturation,

                    "low_saturation": ch.adjustments.low_saturation,

                    "tint": ch.adjustments.tint,

                    "choke": ch.adjustments.choke,

                },

            }

            self._audit.record("channel_adjusted", payload)

            self._events.channel_adjusted.emit(ch.id)

            self._track_edit(
                EditAction.CHANNEL_ADJUSTED,
                channel_id=ch.id,
                channel_name=ch.name,
                before={
                    "choke": original.choke,
                    "high_saturation": original.high_saturation,
                    "low_saturation": original.low_saturation,
                    "tint": original.tint,
                },
                after={
                    "choke": ch.adjustments.choke,
                    "choke_px": ch.adjustments.choke,
                    "high_saturation": ch.adjustments.high_saturation,
                    "low_saturation": ch.adjustments.low_saturation,
                    "tint": ch.adjustments.tint,
                },
            )

            self._view.set_log_message(

                f"Ajustes aplicados em \"{ch.name}\" (choke={ch.adjustments.choke})."

            )

        else:

            ch.set_adjustments(original)

            self.refresh_preview(incremental=False)

    def apply_channel_adjustments(
        self, channel_id: str, adjustments: object, update_ui: bool = False
    ) -> None:
        ch = next((c for c in self._state.channels if c.id == channel_id), None)
        if ch is None or not isinstance(adjustments, ChannelAdjustments):
            return
        ch.set_adjustments(adjustments)
        if update_ui:
            self._view.channels_dock.update_channel(ch)
        self.refresh_preview(incremental=False)



    def reorder_channels(self, ordered_ids: list[str]) -> None:
        old_ids = [channel.id for channel in self._state.channels]
        if old_ids == ordered_ids or reorder_channels(self._state.channels, ordered_ids) is None:
            return
        self._undo.push(ReorderChannelsCommand(old_ids, ordered_ids, self))

        self._audit.record("channel_reordered", {"order": ordered_ids})

        self._track_edit(
            EditAction.CHANNEL_REORDERED,
            before={"order": old_ids},
            after={"order": ordered_ids},
        )

        self._events.channel_reordered.emit()

        self._view.set_log_message("Ordem dos canais atualizada.")

    def apply_channel_order(self, ordered_ids: list[str]) -> None:
        reordered = reorder_channels(self._state.channels, ordered_ids)
        if reordered is None:
            return
        self._state.channels = reordered
        self._view.channels_dock.set_channels(
            reordered, preview_mode=self._state.preview_display_mode
        )
        self.refresh_preview(incremental=True)
        self._events.channel_reordered.emit()



    def merge_channels(self, source_id: str, target_id: str) -> None:
        if source_id == target_id:
            return
        source = next((c for c in self._state.channels if c.id == source_id), None)
        target = next((c for c in self._state.channels if c.id == target_id), None)
        if source is None or target is None or source.mask is None or target.mask is None:
            return

        source_index = next(
            (i for i, c in enumerate(self._state.channels) if c.id == source_id),
            0,
        )
        source_snap = clone_channel(source)
        target_snap = clone_channel(target)
        self._undo.push(
            MergeChannelsCommand(
                source_id,
                target_id,
                source_snap,
                target_snap,
                source_index,
                self,
            )
        )

    def apply_merge_channels(self, source_id: str, target_id: str) -> None:
        source = next((c for c in self._state.channels if c.id == source_id), None)
        merged = merge_channels(self._state.channels, source_id, target_id)
        if merged is None:
            return

        target = next(c for c in merged if c.id == target_id)
        source_name = source.name if source else source_id

        self._state.channels = merged
        self._view.channels_dock.remove_channel(source_id)
        self._view.channels_dock.update_channel(target)
        self.refresh_preview(incremental=False)

        self._audit.record(
            "channel_merged",
            {"source_id": source_id, "target_id": target_id, "result_name": target.name},
        )
        self._track_edit(
            EditAction.CHANNEL_MERGED,
            channel_id=source_id,
            channel_name=source_name,
            target_channel_id=target_id,
            before={"source": source_name, "target_id": target_id},
            after={"result_name": target.name},
        )
        self._events.channel_merged.emit(target_id)
        self._view.set_log_message(f"Canais unidos em \"{target.name}\".")

    def apply_unmerge_channels(
        self,
        source_snap,
        target_snap,
        source_index: int,
    ) -> None:
        target = next((c for c in self._state.channels if c.id == target_snap.id), None)
        if target is None:
            return

        restore_channel_from_clone(target, target_snap)
        source = clone_channel(source_snap)

        channels = list(self._state.channels)
        insert_at = max(0, min(source_index, len(channels)))
        channels.insert(insert_at, source)
        self._state.channels = channels

        self._view.channels_dock.set_channels(
            self._state.channels, preview_mode=self._state.preview_display_mode
        )
        self.refresh_preview(incremental=False)
        self._audit.record(
            "channel_unmerged",
            {
                "source_id": source.id,
                "target_id": target.id,
                "source_name": source.name,
                "target_name": target.name,
            },
        )
        self._events.channel_merged.emit(target.id)
        self._view.set_log_message("Junção desfeita.")



    def change_channel_color(self, channel_id: str) -> None:

        ch = next((c for c in self._state.channels if c.id == channel_id), None)

        if ch is None:

            return

        initial = QColor(*ch.color_rgb)

        picked = QColorDialog.getColor(initial, self._view, "Cor do canal")

        if not picked.isValid():

            return

        old_color = ch.color_rgb
        new_color = (picked.red(), picked.green(), picked.blue())
        self._undo.push(
            SetChannelValueCommand(
                "Alterar cor",
                "apply_channel_color",
                channel_id,
                old_color,
                new_color,
                self,
            )
        )

        self._audit.record(

            "channel_color_changed",

            {"channel_id": channel_id, "name": ch.name, "color_rgb": ch.color_rgb},

        )

        self._track_edit(
            EditAction.CHANNEL_COLOR_CHANGED,
            channel_id=channel_id,
            channel_name=ch.name,
            after={"color_rgb": list(ch.color_rgb)},
        )

        self._view.set_log_message(f"Cor do canal \"{ch.name}\" atualizada.")

    def apply_channel_color(
        self, channel_id: str, color: object, update_ui: bool = False
    ) -> None:
        ch = next((c for c in self._state.channels if c.id == channel_id), None)
        if ch is None or not isinstance(color, tuple) or len(color) != 3:
            return
        set_channel_color(ch, color)
        if update_ui:
            self._view.channels_dock.update_channel(ch)
        self.refresh_preview(incremental=False)



    def delete_channel(self, channel_id: str) -> None:

        ch = next((c for c in self._state.channels if c.id == channel_id), None)

        if ch is None:

            return

        if len(self._state.channels) <= 1:

            QMessageBox.warning(self._view, "Excluir canal", "Deve restar ao menos um canal.")

            return

        reply = QMessageBox.question(

            self._view,

            "Excluir canal",

            f"Excluir o canal \"{ch.name}\"?",

            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,

        )

        if reply != QMessageBox.StandardButton.Yes:

            return

        index = self._state.channels.index(ch)
        name = ch.name
        self._undo.push(DeleteChannelCommand(clone_channel(ch), index, self))

        self._audit.record("channel_deleted", {"channel_id": channel_id, "name": name})

        self._track_edit(
            EditAction.CHANNEL_DELETED,
            channel_id=channel_id,
            channel_name=name,
            before={"visible": True},
            after={},
        )

        self._events.channel_deleted.emit(channel_id)

        self._view.set_log_message(f"Canal \"{name}\" excluído.")

    def duplicate_channel(self, channel_id: str) -> str | None:
        """Duplica a separação logo após a original (com undo). Retorna o id da cópia."""
        ch = next((c for c in self._state.channels if c.id == channel_id), None)
        if ch is None:
            return None
        copy = clone_channel(ch)
        copy.id = str(uuid.uuid4())
        copy.name = f"{ch.name} copy"
        index = self._state.channels.index(ch) + 1
        self._undo.push(InsertChannelCommand(copy, index, self, "Duplicar canal"))
        self._audit.record(
            "channel_duplicated", {"source_id": channel_id, "channel_id": copy.id, "name": copy.name}
        )
        self._view.set_log_message(f"Canal \"{ch.name}\" duplicado.")
        return copy.id

    def apply_delete_channel(self, channel_id: str) -> None:
        updated = delete_channel(self._state.channels, channel_id)
        if updated is None:
            return
        self._state.channels = updated
        self._view.channels_dock.remove_channel(channel_id)
        self.refresh_preview(incremental=False)
        self._events.channel_deleted.emit(channel_id)

    def apply_restore_channel(self, snapshot, index: int) -> None:
        if any(channel.id == snapshot.id for channel in self._state.channels):
            return
        channels = list(self._state.channels)
        channels.insert(max(0, min(index, len(channels))), clone_channel(snapshot))
        self._state.channels = channels
        self._view.channels_dock.set_channels(
            channels, preview_mode=self._state.preview_display_mode
        )
        self.refresh_preview(incremental=False)



    def _refresh_preview_immediate(self) -> None:
        """Preview síncrono — visibilidade e feedback instantâneo sem corrida de thread."""
        doc = self._state.active_document
        if not doc or not self._state.channels:
            return
        preview = self._compose_channel_preview(
            self._state.channels,
            (doc.height, doc.width),
            fast=True,
        )
        if preview is None:
            return
        self._store_result_preview(preview)
        if self._view.canvas.has_result_image():
            self._view.canvas.update_result_from_pil(preview, fast=True)
        else:
            self._view.canvas.set_result_from_pil(preview)

    def refresh_preview(self, *, incremental: bool = False) -> None:

        doc = self._state.active_document

        if not doc or not self._state.channels:

            return



        channels = self._state.channels

        shape = (doc.height, doc.width)

        visibility = self._visibility_snapshot()



        if incremental:

            def _render_fast():

                return self._compose_channel_preview(
                    channels, shape, visibility=visibility, fast=True
                )

            self._submit_preview(_render_fast, interactive=True)
            return

        def _render_full():
            return self._compose_channel_preview(channels, shape, visibility=visibility)

        self._submit_preview(_render_full, interactive=False)



    def set_channels(self, channels: list, *, refresh: bool = True) -> None:

        self._isolation_visibility = None
        self._state.channels = channels

        self._view.channels_dock.set_channels(
            channels,
            preview_mode=self._state.preview_display_mode,
        )

        if refresh:
            # Um único refresh completo: dois submits seguidos reiniciavam o
            # QThread antigo e derrubavam o Qt 6.11.
            self.refresh_preview(incremental=False)


