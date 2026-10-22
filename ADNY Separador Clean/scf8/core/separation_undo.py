from __future__ import annotations

from typing import Protocol

from PySide6.QtGui import QUndoCommand

from packages.core.models.channel_info import ChannelInfo
from packages.core.services.channel_ops import clone_channel
from scf8.core.separation_ops import SeparationEdit


class SeparationsApplier(Protocol):
    def apply_separations_state(self, order: list[str], snapshots: dict[str, ChannelInfo]) -> None: ...


class ReplaceSeparationsCommand(QUndoCommand):
    """Undo/redo de uma operação do menu Separations / Generate Black.

    Guarda a ordem antes/depois e cópias profundas só das separações alteradas,
    removidas ou criadas; as demais continuam sendo as instâncias vivas do documento.
    """

    def __init__(
        self,
        text: str,
        before: list[ChannelInfo],
        edit: SeparationEdit,
        applier: SeparationsApplier,
    ) -> None:
        super().__init__(text)
        touched_before = edit.changed | edit.removed
        touched_after = edit.changed | edit.added
        self._before_order = [ch.id for ch in before]
        self._after_order = [ch.id for ch in edit.channels]
        self._before = {ch.id: clone_channel(ch) for ch in before if ch.id in touched_before}
        self._after = {ch.id: clone_channel(ch) for ch in edit.channels if ch.id in touched_after}
        self._applier = applier

    def undo(self) -> None:
        self._applier.apply_separations_state(self._before_order, self._before)

    def redo(self) -> None:
        self._applier.apply_separations_state(self._after_order, self._after)
