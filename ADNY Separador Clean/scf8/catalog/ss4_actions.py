"""Catálogo enxuto: só Arquivo → Abrir / Salvar + menu de contexto da barra de canais."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

MenuId = Literal[
    "file",
    "edit",
    "separations",
    "proof_positive",
    "generate_black",
    "view",
    "licensing",
    "window",
    "support",
    "tools",
    "main_toolbar",
    "separation_context",
]


class ActionStatus(str, Enum):
    SHIPPED = "shipped"
    STUB = "stub"
    PLANNED = "planned"


class ActionKind(str, Enum):
    ACTION = "action"
    SEPARATION_LIST = "separation_list"
    NEW_WINDOW_MENU = "new_window_menu"
    DOCUMENT_WINDOWS = "document_windows"
    DRAG_ALL = "drag_all"
    ACTIVE_SEPARATIONS = "active_separations"


@dataclass(frozen=True, slots=True)
class Ss4Action:
    action_id: str
    menu: MenuId
    label: str
    description: str
    status: ActionStatus
    handler: str | None = None
    shortcut: str | None = None
    separator_before: bool = False
    checkable: bool = False
    checked: bool = False
    enabled: bool = True
    shortcut_display_only: bool = False
    kind: ActionKind = ActionKind.ACTION
    style: str | None = None


def _a(
    action_id: str,
    menu: MenuId,
    label: str,
    handler: str | None = None,
    shortcut: str | None = None,
    *,
    desc: str = "",
    status: ActionStatus | None = None,
    sep: bool = False,
    checkable: bool = False,
    checked: bool = False,
    enabled: bool = True,
    shortcut_display_only: bool = False,
    kind: ActionKind = ActionKind.ACTION,
    style: str | None = None,
) -> Ss4Action:
    if status is None:
        status = ActionStatus.SHIPPED if handler else ActionStatus.STUB
    return Ss4Action(
        action_id,
        menu,
        label,
        desc or label,
        status,
        handler,
        shortcut,
        separator_before=sep,
        checkable=checkable,
        checked=checked,
        enabled=enabled,
        shortcut_display_only=shortcut_display_only,
        kind=kind,
        style=style,
    )


# Versão Clean: apenas Abrir e Salvar no menu Arquivo.
SS4_ACTIONS: tuple[Ss4Action, ...] = (
    _a(
        "file.open",
        "file",
        "Abrir...",
        "open_file",
        "Ctrl+O",
        desc="Abre a arte e já roda a separação",
    ),
    _a(
        "file.save",
        "file",
        "Salvar",
        "save_document",
        "Ctrl+S",
        desc="PSD com um canal spot por separação",
    ),
    # Contexto da barra de canais (mantido).
    _a(
        "ctx.open_new_window",
        "separation_context",
        "Abrir em nova janela",
        "open_selected_in_new_window",
    ),
    _a(
        "ch.delete",
        "separation_context",
        "Excluir separação",
        "delete_selected_channel",
        sep=True,
    ),
    _a(
        "ch.duplicate",
        "separation_context",
        "Duplicar separação",
        "duplicate_selected_channel",
    ),
    _a(
        "ch.adjust",
        "separation_context",
        "Ajustar separação",
        "adjust_selected_channel",
    ),
    _a(
        "ctx.doc_properties",
        "separation_context",
        "Propriedades do documento...",
        "document_properties",
        sep=True,
    ),
)


MENU_TITLES: dict[MenuId, str] = {
    "file": "Arquivo",
    "edit": "Editar",
    "separations": "Separações",
    "proof_positive": "Prova positiva",
    "generate_black": "Gerar preto",
    "view": "Exibir",
    "licensing": "Licenciamento",
    "window": "Janela",
    "support": "Suporte",
    "tools": "Ferramentas",
    "main_toolbar": "Principal",
    "separation_context": "Separação",
}

MENUBAR_ORDER: tuple[MenuId, ...] = ("file",)


def actions_for_menu(menu: MenuId) -> list[Ss4Action]:
    return [a for a in SS4_ACTIONS if a.menu == menu]


def action_by_id(action_id: str) -> Ss4Action:
    return next(a for a in SS4_ACTIONS if a.action_id == action_id)
