from __future__ import annotations

from PySide6.QtGui import QUndoCommand, QUndoStack


class UndoStackService:
    """Encapsulates QUndoStack outside of widgets."""

    def __init__(self, max_undo: int = 50) -> None:
        self._stack = QUndoStack()
        self._stack.setUndoLimit(max_undo)

    @property
    def stack(self) -> QUndoStack:
        return self._stack

    @property
    def undo_limit(self) -> int:
        return self._stack.undoLimit()

    def set_undo_limit(self, limit: int) -> None:
        """Novo limite de passos; o QUndoStack só aceita trocar o limite com a pilha vazia."""
        limit = max(1, int(limit))
        if limit == self._stack.undoLimit():
            return
        if self._stack.count():
            self._stack.clear()
        self._stack.setUndoLimit(limit)

    def push(self, command: QUndoCommand) -> None:
        self._stack.push(command)

    def undo(self) -> None:
        self._stack.undo()

    def redo(self) -> None:
        self._stack.redo()

    def can_undo(self) -> bool:
        return self._stack.canUndo()

    def can_redo(self) -> bool:
        return self._stack.canRedo()

    def clear(self) -> None:
        self._stack.clear()


class LoadImageCommand(QUndoCommand):
    def __init__(self, presenter: object, path: str, old_state: object | None) -> None:
        super().__init__(f"Abrir {path}")
        self._presenter = presenter
        self._path = path
        self._old_state = old_state
        # QUndoStack.push() chama redo() na hora. O open_image já aplicou o estado —
        # se refizermos o load aqui, nasce outro document.id, a separação em curso
        # é descartada e os canais são limpos (app "fecha"/some após o motor).
        self._applied = True

    def undo(self) -> None:
        self._applied = False
        if hasattr(self._presenter, "restore_state"):
            self._presenter.restore_state(self._old_state)  # type: ignore[attr-defined]

    def redo(self) -> None:
        if self._applied:
            return
        self._applied = True
        if hasattr(self._presenter, "load_image_direct"):
            self._presenter.load_image_direct(self._path)  # type: ignore[attr-defined]


class SetChannelVisibleCommand(QUndoCommand):
    """Set channel visibility without re-entering undo stack."""

    def __init__(
        self,
        channel_id: str,
        old_visible: bool,
        new_visible: bool,
        applier: object,
    ) -> None:
        super().__init__("Alternar canal")
        self._channel_id = channel_id
        self._old_visible = old_visible
        self._new_visible = new_visible
        self._applier = applier

    def undo(self) -> None:
        if hasattr(self._applier, "apply_channel_visible"):
            self._applier.apply_channel_visible(  # type: ignore[attr-defined]
                self._channel_id, self._old_visible, update_ui=True
            )

    def redo(self) -> None:
        if hasattr(self._applier, "apply_channel_visible"):
            self._applier.apply_channel_visible(  # type: ignore[attr-defined]
                self._channel_id, self._new_visible, update_ui=True
            )


class MergeChannelsCommand(QUndoCommand):
    """Une dois canais com undo que restaura origem e alvo ao estado pré-junção."""

    def __init__(
        self,
        source_id: str,
        target_id: str,
        source_snap: object,
        target_snap: object,
        source_index: int,
        applier: object,
    ) -> None:
        super().__init__("Unir canais")
        self._source_id = source_id
        self._target_id = target_id
        self._source_snap = source_snap
        self._target_snap = target_snap
        self._source_index = source_index
        self._applier = applier

    def undo(self) -> None:
        if hasattr(self._applier, "apply_unmerge_channels"):
            self._applier.apply_unmerge_channels(  # type: ignore[attr-defined]
                self._source_snap,
                self._target_snap,
                self._source_index,
            )

    def redo(self) -> None:
        if hasattr(self._applier, "apply_merge_channels"):
            self._applier.apply_merge_channels(  # type: ignore[attr-defined]
                self._source_id,
                self._target_id,
            )


class SetChannelValueCommand(QUndoCommand):
    """Comando reversível para cor, opacidade ou ajustes de um canal."""

    def __init__(
        self,
        text: str,
        method_name: str,
        channel_id: str,
        old_value: object,
        new_value: object,
        applier: object,
    ) -> None:
        super().__init__(text)
        self._method_name = method_name
        self._channel_id = channel_id
        self._old_value = old_value
        self._new_value = new_value
        self._applier = applier

    def _apply(self, value: object) -> None:
        method = getattr(self._applier, self._method_name, None)
        if method is not None:
            method(self._channel_id, value, update_ui=True)

    def undo(self) -> None:
        self._apply(self._old_value)

    def redo(self) -> None:
        self._apply(self._new_value)


class ReorderChannelsCommand(QUndoCommand):
    def __init__(self, old_ids: list[str], new_ids: list[str], applier: object) -> None:
        super().__init__("Reordenar canais")
        self._old_ids = list(old_ids)
        self._new_ids = list(new_ids)
        self._applier = applier

    def undo(self) -> None:
        self._applier.apply_channel_order(self._old_ids)  # type: ignore[attr-defined]

    def redo(self) -> None:
        self._applier.apply_channel_order(self._new_ids)  # type: ignore[attr-defined]


class InsertChannelCommand(QUndoCommand):
    """Insere um canal (ex.: duplicar separação); desfazer remove o canal inserido."""

    def __init__(self, snapshot: object, index: int, applier: object, text: str = "Duplicar canal") -> None:
        super().__init__(text)
        self._snapshot = snapshot
        self._index = index
        self._applier = applier

    def undo(self) -> None:
        self._applier.apply_delete_channel(  # type: ignore[attr-defined]
            self._snapshot.id
        )

    def redo(self) -> None:
        self._applier.apply_restore_channel(  # type: ignore[attr-defined]
            self._snapshot, self._index
        )


class DeleteChannelCommand(QUndoCommand):
    def __init__(self, snapshot: object, index: int, applier: object) -> None:
        super().__init__("Excluir canal")
        self._snapshot = snapshot
        self._index = index
        self._applier = applier

    def undo(self) -> None:
        self._applier.apply_restore_channel(  # type: ignore[attr-defined]
            self._snapshot, self._index
        )

    def redo(self) -> None:
        self._applier.apply_delete_channel(  # type: ignore[attr-defined]
            self._snapshot.id
        )
