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
    # Itens montados em tempo de execução a partir das separações do documento.
    SEPARATION_LIST = "separation_list"
    NEW_WINDOW_MENU = "new_window_menu"
    DOCUMENT_WINDOWS = "document_windows"
    # Widgets da barra superior (não são QAction com rótulo).
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
    # Atalho só exibido no menu (WidgetShortcut): conflito Generate Brown × Fechar documento.
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


PRINT_UNAVAILABLE = "Impressão indisponível nesta versão"

# Rótulos em português do Brasil (estamparia/serigrafia) — não usar português de Portugal.
SS4_ACTIONS: tuple[Ss4Action, ...] = (
    # Arquivo
    _a("file.open", "file", "Abrir...", "open_file", "Ctrl+O",
       desc="Abre a arte e já roda a separação"),
    _a("file.close_window", "file", "Fechar janela", "close_window", "Ctrl+F4"),
    _a("file.close", "file", "Fechar documento", "close_document", "Ctrl+Shift+W"),
    _a("file.close_all", "file", "Fechar todos os documentos", "close_all_documents", "Ctrl+Alt+W"),
    _a("file.save", "file", "Salvar", "save_document", "Ctrl+S", sep=True,
       desc="PSD com um canal spot por separação"),
    _a("file.save_as", "file", "Salvar como...", "save_document_as",
       desc="PSD com canais spot, com outro nome"),
    _a("file.export", "file", "Exportar...", "export_separations", sep=True,
       desc="DCS 2.0 EPS (uma chapa por separação) ou um PNG por separação"),
    _a("file.save_proof", "file", "Salvar prova de cor", "save_color_proof", sep=True,
       desc="Salva a prova positiva (BMP, PNG, JPEG ou TIFF)"),
    _a("file.proof_page_setup", "file", "Configurar página da prova", "color_proof_page_setup", sep=True,
       desc=PRINT_UNAVAILABLE, enabled=False),
    _a("file.print_proof", "file", "Imprimir prova de cor", "print_color_proof",
       desc=PRINT_UNAVAILABLE, enabled=False),
    _a("file.print", "file", "Imprimir...", "open_print_commander", "Ctrl+P", sep=True,
       desc=PRINT_UNAVAILABLE, enabled=False),
    _a("file.quit", "file", "Sair", "quit_app", sep=True),
    # Editar
    _a("edit.undo", "edit", "Desfazer", "undo", "Ctrl+Z"),
    _a("edit.redo", "edit", "Refazer", "redo", "Ctrl+Y"),
    _a("edit.deselect", "edit", "Desfazer seleção", "deselect", "Ctrl+D", sep=True),
    _a("edit.inverse", "edit", "Inverter seleção", "inverse_selection", "Ctrl+Shift+I",
       desc="Seleciona tudo menos a seleção atual"),
    _a("edit.delete", "edit", "Apagar", "delete_selection", "Del",
       desc="Apaga a seleção nas separações ativas"),
    _a("edit.inks", "edit", "Tintas...", "edit_ink_library", sep=True,
       desc="Tintas personalizadas: incluir, editar e remover da biblioteca"),
    _a("edit.textiles", "edit", "Tecidos...", "edit_custom_textiles",
       desc="Tecidos personalizados (Preto e Branco já vêm de fábrica)"),
    _a("edit.printer_settings", "edit", "Configurações da impressora...", "default_printer_settings",
       "Ctrl+E", sep=True, desc=PRINT_UNAVAILABLE, enabled=False),
    # Separações
    _a("sep.enhance_red", "separations", "Reforçar vermelho-laranja", "enhance_red_orange",
       "Ctrl+Shift+R", desc="Estica o vermelho nas misturas vermelho/laranja"),
    _a("sep.generate_brown", "separations", "Gerar marrom", "generate_brown", "Ctrl+Shift+W",
       sep=True, shortcut_display_only=True,
       desc="Cria a separação Marrom 470 nas áreas quentes escuras"),
    _a("sep.merge_gray", "separations", "Mesclar cinza", "merge_gray", "Ctrl+Shift+G", sep=True,
       desc="Junta o cinza no branco final"),
    _a("sep.merge_purple", "separations", "Mesclar roxo", "merge_purple", "Ctrl+Shift+P",
       desc="Parte o roxo entre vermelho e azul"),
    _a("sep.merge_turquoise", "separations", "Mesclar turquesa", "merge_turquoise", "Ctrl+Shift+T",
       desc="Junta o turquesa no azul"),
    _a("sep.create_underbase", "separations", "Criar base branca...", "create_underbase", sep=True,
       desc="Cria a base branca ou atualiza a que já existe"),
    _a("sep.pressfit", "separations", "Encaixe na mesa...", "press_fit",
       desc="Agrupa separações para caber nas telas da mesa/carrossel"),
    _a("sep.adjust_all", "separations", "Ajustar separações...", "adjust_separations", "Ctrl+J",
       sep=True, desc="Ajuste por faixa de saturação nas separações ativas"),
    _a("sep.auto_adjust", "separations", "Ajuste automático", "auto_adjust", sep=True,
       desc="Faixa de saturação pronta nas separações de cor"),
    # Prova positiva
    _a("proof.toggle_sep", "proof_positive", "Separações", "set_separation_visible",
       kind=ActionKind.SEPARATION_LIST, desc="Lista com marca, uma por separação"),
    _a("proof.hide_all", "proof_positive", "Ocultar todas as separações", "hide_all_separations"),
    _a("proof.show_all", "proof_positive", "Mostrar todas as separações", "show_all_separations"),
    # Gerar preto
    _a("black.skeletal", "generate_black", "Esquelético...", "generate_black_skeletal",
       desc="Preto de arquivo: forte nas sombras (tecido escuro, sem preto)"),
    _a("black.detailed", "generate_black", "Detalhado...", "generate_black_detailed",
       desc="Preto de arquivo: melhor controle nos meios-tons"),
    _a("black.sharper", "generate_black", "Mais nítido...", "generate_black_sharper",
       desc="Preto de arquivo: máximo de detalhe (tecido médio a claro)"),
    # Exibir
    _a("view.zoom_in", "view", "Aumentar zoom", "zoom_in", "Ctrl++"),
    _a("view.zoom_out", "view", "Diminuir zoom", "zoom_out", "Ctrl+-"),
    _a("view.zoom_fill", "view", "Preencher a janela", "zoom_fill_window", "Ctrl+Alt+0"),
    _a("view.fit", "view", "Cabendo na tela", "fit_on_screen", "Ctrl+0"),
    _a("view.actual", "view", "Pixels reais", "actual_pixels", "Ctrl+1"),
    _a("view.match_zoom", "view", "Igualar zoom", "match_zoom", sep=True,
       desc="Copia o zoom da janela ativa para as outras"),
    _a("view.toggle_sep", "view", "Separações", "set_separation_visible", sep=True,
       kind=ActionKind.SEPARATION_LIST),
    _a("view.hide_all", "view", "Ocultar todas as separações", "hide_all_separations"),
    _a("view.show_all", "view", "Mostrar todas as separações", "show_all_separations"),
    _a("view.textile_color", "view", "Mostrar cor do tecido", "toggle_textile_color",
       checkable=True, checked=True),
    _a("view.adjust_separation", "view", "Ajustar separação...", "adjust_selected_channel"),
    _a("view.doc_properties", "view", "Propriedades do documento...", "document_properties", sep=True),
    _a("view.textile", "view", "Tecido...", "edit_ground"),
    # Licenciamento
    _a("lic.info", "licensing", "Informações da licença...", enabled=False),
    # Janela
    _a("win.lock_toolbars", "window", "Travar barras de ferramentas", "toggle_lock_toolbars",
       "Ctrl+L", checkable=True, checked=True),
    _a("win.cascade", "window", "Em cascata", "cascade_windows", sep=True),
    _a("win.tile", "window", "Lado a lado", "tile_windows"),
    _a("win.new_window", "window", "Nova janela", "open_in_new_window", sep=True,
       kind=ActionKind.NEW_WINDOW_MENU,
       desc="Abre a prova positiva ou uma separação em outra janela"),
    _a("win.documents", "window", "Documentos", "focus_vue_rite", sep=True,
       kind=ActionKind.DOCUMENT_WINDOWS, desc="Uma entrada por janela aberta"),
    # Suporte
    _a("support.preferences", "support", "Preferências...", "open_preferences"),
    _a("support.user_guides", "support", "Guias do usuário...", "open_user_guides"),
    _a("support.technical", "support", "Suporte técnico..."),
    _a("support.secure_agent", "support", "Login do agente seguro..."),
    _a("support.wish_list", "support", "Lista de desejos..."),
    _a("support.about", "support", "Sobre...", "show_about"),
    # Ferramentas
    _a("tool.move", "tools", "Arrastar", "tool_move", checkable=True, checked=True,
       desc="Arrasta a imagem ampliada pela janela"),
    _a("tool.zoom", "tools", "Zoom", "tool_zoom", checkable=True,
       desc="Clique: aumenta · Alt+clique / botão direito: diminui"),
    _a("tool.lasso", "tools", "Laço", "tool_lasso", checkable=True, desc="Seleção à mão livre"),
    _a("tool.poly_lasso", "tools", "Laço poligonal", "tool_poly_lasso", checkable=True,
       desc="Clique em cada canto; clique duplo fecha"),
    _a("tool.rect_select", "tools", "Selecionar área", "tool_rect_select", checkable=True,
       desc="Clique e arraste um retângulo"),
    _a("tool.saturate", "tools", "Encharcar", "tool_saturate", checkable=True,
       desc="Passa o pincel: carrega mais tinta nas separações ativas"),
    _a("tool.desaturate", "tools", "Aliviar tinta", "tool_desaturate", checkable=True,
       desc="Passa o pincel: tira tinta das separações ativas"),
    _a("tool.eraser", "tools", "Borracha", "tool_eraser", checkable=True,
       desc="Passa a borracha: remove dados das separações ativas"),
    # Barra principal
    _a("tb.open", "main_toolbar", "Abrir...", "open_file", style="green"),
    _a("tb.close", "main_toolbar", "Fechar", "close_document", style="red"),
    _a("tb.save", "main_toolbar", "Salvar", "save_document"),
    _a("tb.textile", "main_toolbar", "Tecido...", "edit_ground"),
    _a("tb.underbase", "main_toolbar", "Base branca...", "create_underbase"),
    _a("tb.pressfit", "main_toolbar", "Encaixe na mesa...", "press_fit"),
    _a("tb.auto_adjust", "main_toolbar", "Ajuste automático", "auto_adjust"),
    _a("tb.print", "main_toolbar", "Imprimir...", "open_print_commander",
       desc=PRINT_UNAVAILABLE, enabled=False),
    _a("tb.drag_all", "main_toolbar", "Arrastar todas as janelas", "toggle_drag_all_windows",
       sep=True, kind=ActionKind.DRAG_ALL),
    _a("tb.active_seps", "main_toolbar", "Separações ativas:", "set_separation_active", sep=True,
       kind=ActionKind.ACTIVE_SEPARATIONS),
    _a("tb.select_all", "main_toolbar", "Marcar todas", "select_all_active"),
    _a("tb.deselect_all", "main_toolbar", "Desmarcar todas", "deselect_all_active"),
    # Contexto da miniatura
    _a("ctx.open_new_window", "separation_context", "Abrir em nova janela",
       "open_selected_in_new_window"),
    _a("ch.delete", "separation_context", "Excluir separação", "delete_selected_channel", sep=True),
    _a("ch.duplicate", "separation_context", "Duplicar separação", "duplicate_selected_channel"),
    _a("ch.adjust", "separation_context", "Ajustar separação", "adjust_selected_channel"),
    _a("ctx.doc_properties", "separation_context", "Propriedades do documento...",
       "document_properties", sep=True),
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

MENUBAR_ORDER: tuple[MenuId, ...] = (
    "file",
    "edit",
    "separations",
    "proof_positive",
    "generate_black",
    "view",
    "licensing",
    "window",
    "support",
)


def actions_for_menu(menu: MenuId) -> list[Ss4Action]:
    return [a for a in SS4_ACTIONS if a.menu == menu]


def action_by_id(action_id: str) -> Ss4Action:
    return next(a for a in SS4_ACTIONS if a.action_id == action_id)
