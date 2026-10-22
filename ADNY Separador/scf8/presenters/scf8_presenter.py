from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

from apps.desktop_qt.canvases.image_view import CanvasTool
from apps.desktop_qt.presenters.main_presenter import MainPresenter
from packages.core.models.channel_info import ChannelInfo
from packages.core.models.preview_display import PreviewDisplayMode
from packages.core.services.channel_ops import clone_channel, restore_channel_from_clone
from scf8.branding import (
    APP_SUBTITLE,
    APP_NAME,
    APP_NAME_SHORT,
    GENERATED_VIEW_TITLE,
    ORIGINAL_VIEW_TITLE,
    PROOF_VIEW_TITLE,
)
from scf8.catalog.ss4_actions import SS4_ACTIONS, ActionStatus, Ss4Action
from scf8.core import canvas_ops as cops
from scf8.core import separation_ops as ops
from scf8.core.naming import separation_display_name, separation_psd_name
from scf8.core.psd_save_tuning import (
    APPLY_DIVISION_ON_PSD_SAVE,
    is_psd_division_target,
    photoshop_apply_image_divide_self,
)
from scf8.core.separation_undo import ReplaceSeparationsCommand
from scf8.core.ss4_separation_preset import spot_process_ss4_params
from scf8.services.underbase import (
    LiveUnderbaseSettings,
    UnderbaseMode,
    find_underbase,
    is_underbase_channel,
    live_underbase_mask,
)
from scf8.ui.document_area import ORIGINAL_VIEW, PROOF_VIEW, separation_plate
from scf8.ui.preferences_dialog import (
    DEFAULT_PRESS_SIZE,
    DEFAULT_UNDO_LIMIT,
    DEFAULT_VIEW,
    PreferencesDialog,
)
from scf8.ui.printer_settings_dialog import (
    DEFAULT_PREFERENCES_PATH,
    PrinterSettingsDialog,
    load_printer_defaults,
    save_printer_defaults,
)
from scf8.ui.saturation_range_dialog import SaturationRangeDialog
from scf8.ui.separation_dialogs import PressFitDialog
from scf8.ui.underbase_dialog import LiveUnderbaseDialog

logger = logging.getLogger(__name__)

IN_DEVELOPMENT = "em desenvolvimento"
USER_GUIDE = Path(__file__).resolve().parents[2] / "docs" / "user_guide.html"
# Intervalo mínimo entre previews durante um traço de pincel (o traço inteiro é aplicado ao soltar).
_STROKE_PREVIEW_INTERVAL_S = 0.06

BLACK_FILE_FILTER = "Imagens (*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.psd)"
PROOF_FILE_FILTER = "BMP (*.bmp);;PNG (*.png);;JPEG (*.jpg);;TIFF (*.tif)"
EXPORT_FILE_FILTER = "EPS DCS 2.0 (*.eps);;PNG por separação (*.png)"
_PROOF_FORMATS = {".bmp": "BMP", ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".tif": "TIFF", ".tiff": "TIFF"}
_BRUSH_TITLES = {"saturate": "Encharcar", "desaturate": "Aliviar tinta", "eraser": "Borracha"}


@dataclass
class _UnderbaseLink:
    """Underbase criada pela janela Live Underbase Properties (uma por documento)."""

    settings: LiveUnderbaseSettings
    mode: UnderbaseMode
    command: Any
    checksum: float | None
    signature: tuple
    epoch: int
    detached: bool = False


def _mask_checksum(channel: ChannelInfo | None) -> float | None:
    if channel is None or channel.mask is None:
        return None
    return round(float(np.asarray(channel.mask, dtype=np.float64).sum()), 3)


def _separations_signature(channels: list[ChannelInfo]) -> tuple:
    return tuple(
        (ch.id, ch.mask.shape, round(float(np.asarray(ch.mask, dtype=np.float64).sum()), 3))
        for ch in channels
        if ch.mask is not None and not is_underbase_channel(ch)
    )


class Scf8Presenter:
    """Interface scf8 → separação FAV8+ preset Spot Process."""

    def __init__(self, view: Any) -> None:
        self._view = view
        self._core = MainPresenter(view)
        self._densitometer_enabled = True
        self._channel_print: dict[str, bool] = {}
        self._ink_snapshot: dict | None = None
        # Active Separations: guarda as desativadas, assim separações novas nascem ativas.
        self._inactive_ids: set[str] = set()
        self._save_path: str | None = None
        self._drag_all_windows = False
        self._toolbars_locked = True
        # Live Underbase Properties: vínculo por documento e a Underbase que o motor gerou (teto da Live).
        self._underbase_links: dict[str, _UnderbaseLink] = {}
        self._engine_underbase: dict[str, np.ndarray | None] = {}
        self._undo_epoch = 0
        self._core.undo_service.stack.indexChanged.connect(self._on_undo_index_changed)
        self._live_timer = QTimer()
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(0)
        self._live_timer.timeout.connect(self.sync_underbase_link)
        self._lab_cache: tuple[str, ops.ImageLab] | None = None
        self._stroke: cops.BrushStroke | None = None
        self._stroke_before: dict[str, Any] = {}
        self._stroke_preview_at = 0.0
        # Barra Tool Options (Saturate / Desaturate / Eraser).
        self.brush_hardness = cops.DEFAULT_HARDNESS
        self.brush_range: cops.SaturationRange = cops.DEFAULT_RANGE
        self.brush_flow = cops.DEFAULT_FLOW
        # Preferences do SS4.
        self.default_view = DEFAULT_VIEW
        self.undo_limit = DEFAULT_UNDO_LIMIT
        self.press_size = DEFAULT_PRESS_SIZE
        self._core.undo_service.set_undo_limit(self.undo_limit)
        self.preferences_path: Path = DEFAULT_PREFERENCES_PATH
        self._printer = None
        # Layout da prova de cor (Color Proof Page Setup), usado em Print Color Proof.
        self.proof_page_layout = None

    @property
    def project_state(self):
        return self._core.project_state

    def _ss4_params(self) -> dict:
        if self._ink_snapshot is None:
            self._ink_snapshot = self._core._ink_library.load().to_dict()
        return spot_process_ss4_params(
            textile_dark=self._view.params_dock.dark_fabric_cb.isChecked(),
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

    # ------------------------------------------------------------ File
    def open_file(self) -> None:
        """SS4: Open raster → separação Spot Process automática."""
        from packages.image.io import OPEN_FILE_FILTER

        path, _ = QFileDialog.getOpenFileName(
            self._view,
            "Abrir",
            "",
            OPEN_FILE_FILTER,
        )
        if not path:
            return
        self._view.set_log_message("Carregando…")
        self._core.open_image(path)
        doc = self.project_state.active_document
        # open_image engole o erro e mostra o diálogo — só roda o motor se carregou este arquivo
        if doc is None or not doc.path or Path(doc.path).resolve() != Path(path).resolve():
            self._view.set_log_message("Falha ao abrir.")
            return
        self._save_path = None
        self._inactive_ids.clear()
        self._forget_document_edits()
        self._sync_view()
        self._view.set_log_message("Separação Spot Process (FAV8+) — a interface continua responsiva…")
        QTimer.singleShot(80, self.run_separation)

    def _forget_document_edits(self) -> None:
        self._forget_underbase()
        self._lab_cache = None
        self._stroke = None
        self._stroke_before = {}

    def _forget_underbase(self) -> None:
        self._underbase_links.clear()
        self._engine_underbase.clear()

    def run_separation(self) -> None:
        self._forget_underbase()
        self._core.separate_channels(self._ss4_params(), prompt_engine=False)

    def document_name(self) -> str | None:
        doc = self.project_state.active_document
        if doc is None:
            return None
        return Path(doc.path).name if doc.path else "Sem título"

    def document_title(self) -> str | None:
        if self.project_state.active_document is None:
            return None
        if self.project_state.channels:
            return GENERATED_VIEW_TITLE
        name = self.document_name()
        return f"{name} : {PROOF_VIEW_TITLE}" if name else None

    def render_document_view(self, kind: str) -> tuple[str, Any] | None:
        """Título e imagem de uma janela: original, composite ou chapa de separação."""
        state = self.project_state
        doc = state.active_document
        if doc is None:
            return None
        name = self.document_name()
        if kind == ORIGINAL_VIEW:
            image = doc.pil_image
            return (ORIGINAL_VIEW_TITLE, image) if image is not None else None
        if kind == PROOF_VIEW:
            image = self._view.canvas.display_image()
            return (f"{name} : {PROOF_VIEW_TITLE}", image) if image is not None else None
        channel = next((ch for ch in state.channels if ch.id == kind), None)
        if channel is None or channel.mask is None:
            return None
        film = state.preview_display_mode == PreviewDisplayMode.FILM
        plate = separation_plate(channel.mask, None if film else channel.color_rgb)
        return f"{name} : {self._channel_label(channel)}", plate

    def has_open_work(self) -> bool:
        """Há arte ou separações na área de trabalho."""
        state = self.project_state
        return state.active_document is not None or bool(state.channels)

    def prompt_save_before_quit(self) -> bool:
        """Pergunta se salva antes de sair. True = pode fechar; False = permanece aberto."""
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
        import logging

        logging.getLogger(__name__).info(
            "close_document chamado", stack_info=True
        )
        self._core.restore_state({})
        self._view.channels_dock.set_channels([])
        self._view.canvas.set_original_from_pil(None)
        self._view.canvas.set_result_from_pil(None)
        self._channel_print.clear()
        self._inactive_ids.clear()
        self._forget_document_edits()
        self._save_path = None
        self._view.update_status_bar()
        self._sync_view()
        self._view.set_log_message("Documento fechado.")

    def close_window(self) -> None:
        """Close Window: fecha a janela ativa; a janela Proof Positive principal fecha o documento."""
        documents = self._documents()
        if documents is not None and documents.close_current_extra():
            self._view.set_log_message("Janela fechada.")
            return
        self.close_document()

    def close_all_documents(self) -> None:
        self.close_document()

    def save_document(self) -> bool:
        """Salva o PSD (um canal spot por separação). True se gravou; False se cancelou ou falhou."""
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

    def save_psd(self) -> bool:
        return self.save_document_as()

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

    def export_separations(self) -> None:
        """File > Export...: DCS 2.0 EPS (uma placa spot por separação) ou um PNG por separação."""
        state = self.project_state
        doc = state.active_document
        if not state.channels or doc is None:
            QMessageBox.warning(self._view, "Exportar", "Abra uma arte primeiro.")
            return
        source = Path(doc.path) if doc.path else None
        folder = source.parent if source else Path.home()
        stem = source.stem if source else "Sem título"
        path, selected = QFileDialog.getSaveFileName(
            self._view, "Exportar", str(folder / f"{stem}.eps"), EXPORT_FILE_FILTER
        )
        if not path:
            return
        suffix = Path(path).suffix.lower()
        if suffix not in (".eps", ".png"):
            suffix = ".png" if (selected or "").upper().startswith("PNG") else ".eps"
            path += suffix
        if suffix == ".png":
            out_dir = Path(path).parent
            written = self._core._export_service.export_channels_as_pngs(state.channels, out_dir)
            self._view.set_log_message(f"{len(written)} separação(ões) exportada(s) em PNG em {out_dir}.")
            return
        self._write_dcs(path)

    def _write_dcs(self, path: str) -> bool:
        from packages.image.textile import ground_color_for_state
        from scf8.core.dcs_export import DcsPlate, write_dcs2

        state = self.project_state
        doc = state.active_document
        plates = [
            DcsPlate(self._channel_label(ch), np.asarray(ch.mask, dtype=np.float32), tuple(ch.color_rgb))
            for ch in state.channels
            if ch.mask is not None and tuple(ch.mask.shape[:2]) == (doc.height, doc.width)
        ]
        composite = state.result_document.pil_image if state.result_document else None
        if composite is None or composite.size != (doc.width, doc.height):
            composite = self._view.canvas.display_image()
        if composite is None:
            composite = doc.pil_image
        if composite.size != (doc.width, doc.height):
            composite = composite.resize((doc.width, doc.height))
        self._view.set_log_message("Exportando EPS DCS 2.0…")
        try:
            write_dcs2(path, plates, composite, dpi=self._document_dpi(), ground_rgb=ground_color_for_state(state),
                       title=self.document_name() or Path(path).stem)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self._view, "Exportar", f"Não foi possível exportar o arquivo DCS 2.0:\n{exc}")
            return False
        self._view.set_log_message(f"EPS DCS 2.0 exportado ({len(plates)} chapas): {path}")
        return True

    def save_color_proof(self) -> None:
        """File > Save Color Proof: 'Save your Proof Positive' — BMP padrão, também PNG/JPEG/TIFF."""
        doc = self.project_state.active_document
        image = self._view.canvas.display_image()
        if doc is None or image is None:
            QMessageBox.warning(self._view, "Salvar prova de cor", "Abra uma arte primeiro.")
            return
        source = Path(doc.path) if doc.path else None
        folder = source.parent if source else Path.home()
        stem = source.stem if source else "Sem título"
        path, selected = QFileDialog.getSaveFileName(
            self._view, f"Salvar {PROOF_VIEW_TITLE.lower()}", str(folder / f"{stem}.bmp"), PROOF_FILE_FILTER
        )
        if not path:
            return
        fmt = _PROOF_FORMATS.get(Path(path).suffix.lower())
        if fmt is None:
            ext = next((e for e, f in _PROOF_FORMATS.items() if (selected or "").upper().startswith(f[:3])), ".bmp")
            path, fmt = path + ext, _PROOF_FORMATS[ext]
        try:
            image.convert("RGB").save(path, fmt)
        except OSError as exc:
            QMessageBox.warning(self._view, "Salvar prova de cor", f"Não foi possível salvar a prova:\n{exc}")
            return
        self._view.set_log_message(f"{PROOF_VIEW_TITLE} salva: {path}")

    def _proof_printer(self):
        from PySide6.QtPrintSupport import QPrinter

        if self._printer is None:
            # O driver da impressora padrão (às vezes de rede) pode levar segundos para responder.
            self._view.set_log_message("Conectando à impressora padrão…")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            finally:
                QApplication.restoreOverrideCursor()
        if self.proof_page_layout is not None:
            self._printer.setPageLayout(self.proof_page_layout)
        return self._printer

    def color_proof_page_setup(self) -> None:
        """File > Color Proof Page Setup: papel, orientação e margens da prova de cor."""
        from PySide6.QtGui import QPageLayout
        from PySide6.QtPrintSupport import QPageSetupDialog

        printer = self._proof_printer()
        dialog = QPageSetupDialog(printer, self._view)
        dialog.setWindowTitle("Configurar página da prova de cor")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.proof_page_layout = QPageLayout(printer.pageLayout())
        layout = self.proof_page_layout
        orientation = "paisagem" if layout.orientation() == QPageLayout.Orientation.Landscape else "retrato"
        self._view.set_log_message(f"Página da prova: {layout.pageSize().name()}, {orientation}.")

    def print_color_proof(self) -> None:
        """File > Print Color Proof: imprime o composite (Proof Positive) com o layout da prova."""
        from PySide6.QtPrintSupport import QPrintDialog

        from scf8.ui.color_proof import paint_color_proof

        image = self._view.canvas.display_image()
        if self.project_state.active_document is None or image is None:
            QMessageBox.warning(self._view, "Imprimir prova de cor", "Abra uma arte primeiro.")
            return
        printer = self._proof_printer()
        printer.setDocName(self.document_title() or "Prova de cor")
        dialog = QPrintDialog(printer, self._view)
        dialog.setWindowTitle("Imprimir prova de cor")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if paint_color_proof(printer, image):
            nome = printer.printerName() or "impressora"
            self._view.set_log_message(f"Prova de cor enviada para {nome}.")
        else:
            QMessageBox.warning(self._view, "Imprimir prova de cor", "Não foi possível iniciar a impressão.")

    def open_print_commander(self) -> None:
        from scf8.ui.print_commander_dialog import PrintCommanderDialog

        PrintCommanderDialog(self._view, self).exec()

    def export_films_from_commander(self) -> None:
        self._core.export_films_pdf()

    def quit_app(self) -> None:
        """Arquivo > Sair — o closeEvent pergunta se salva quando há trabalho aberto."""
        self._view.close()

    # ------------------------------------------------------------ Edit
    def deselect(self) -> None:
        self._view.canvas.clear_selection()

    def inverse_selection(self) -> None:
        """Edit > Inverse Selection: imagem inteira menos a seleção atual."""
        if not self._view.canvas.invert_selection():
            self._view.set_log_message("Inverter seleção: nada selecionado.")
            return
        bbox = self._view.canvas.get_selection_bbox()
        self._view.set_log_message(f"Seleção invertida: {bbox}." if bbox else "Seleção invertida: vazia.")

    def delete_selection(self) -> None:
        """Edit > Delete: apaga a tinta das separações ativas dentro da seleção."""
        channels = self._require_separations("Excluir")
        if channels is None:
            return
        doc = self.project_state.active_document
        selection = self._view.canvas.get_selection_mask((doc.height, doc.width))
        if selection is None or not selection.any():
            QMessageBox.information(self._view, "Excluir", "Selecione uma área primeiro.")
            return
        ids = self.active_separation_ids()
        if not ids:
            QMessageBox.information(
                self._view, "Excluir", "Nenhuma separação ativa: marque uma em Separações ativas."
            )
            return
        edit = cops.erase_selection(channels, ids, selection)
        self._commit_edit("Excluir", edit, "Não há tinta das separações ativas dentro da seleção.")

    def default_printer_settings(self) -> None:
        """Edit > Default Printer Settings...: padrões de saída gravados nas preferências."""
        dialog = PrinterSettingsDialog(self._view, load_printer_defaults(self.preferences_path))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        save_printer_defaults(values, self.preferences_path)
        self._view.set_log_message(
            f"Impressora padrão: {values.printer}, {values.media}, {values.dpi} dpi, "
            f"{values.lpi} lpi @ {values.angle:g}°."
        )

    def edit_ground(self) -> None:
        """View > Textile... / botão Textile...: tecido do documento (presets + Custom Textiles) e cor do fundo."""
        from scf8.ui.ground_color_dialog import GroundColorDialog

        state = self.project_state
        dialog = GroundColorDialog(
            self._view, preset=state.textile_preset, custom_rgb=state.ground_rgb_override,
            textiles=self.custom_textiles_entries(),
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        preset = dialog.selected_preset()
        if preset is None:
            rgb = dialog.custom_rgb() or dialog.ground_rgb()
            self._core.set_custom_ground_color(rgb)
            textile = dialog.selected_textile()
            self._view.set_log_message(f"Tecido: {textile} {rgb}" if textile else f"Tecido: RGB personalizado {rgb}")
        else:
            self._core.set_textile_preset(preset.value)
            self._view.set_log_message(f"Tecido: {preset.value}")
        if not state.show_textile_color:
            self.set_show_textile_color(True)

    def edit_ink_library(self) -> None:
        """Edit > Inks...: janela Custom Inks; as tintas aceitas vão para a biblioteca de tintas do app."""
        from scf8.services.custom_libraries import load_custom_inks, save_custom_inks
        from scf8.ui.custom_colors_dialog import CustomColorsDialog

        service = self._core._ink_library

        def persist(entries) -> None:
            save_custom_inks(service, entries)
            self._ink_snapshot = None

        dialog = CustomColorsDialog(
            self._view, title="Tintas personalizadas", prefix="ink", entries=load_custom_inks(service),
            on_change=persist, new_name="Tinta personalizada", empty_text="Clique em + para adicionar uma tinta",
            help_text="Clique em + para adicionar, ▼ para editar e X para remover.\n"
                      "As tintas aceitas vão para a biblioteca e entram na próxima separação.",
        )
        dialog.exec()
        self._ink_snapshot = None
        self._view.set_log_message(f"Tintas personalizadas: {len(dialog.entries())} tinta(s) na biblioteca.")

    def custom_textiles_entries(self) -> list[tuple[str, tuple[int, int, int]]]:
        from scf8.services.custom_libraries import load_custom_textiles

        return load_custom_textiles(self.preferences_path)

    def custom_textiles(self) -> list[dict]:
        """Biblioteca de tecidos (Custom Textiles) gravada nas preferências."""
        return [{"name": name, "rgb": list(rgb)} for name, rgb in self.custom_textiles_entries()]

    def edit_custom_textiles(self) -> None:
        """Edit > Textiles...: janela Custom Textiles (biblioteca de tecidos; Black e White padrão)."""
        from scf8.services.custom_libraries import save_custom_textiles
        from scf8.ui.custom_colors_dialog import (
            CUSTOM_TEXTILES_EMPTY,
            CUSTOM_TEXTILES_HELP,
            CUSTOM_TEXTILES_NEW_NAME,
            CUSTOM_TEXTILES_TITLE,
            CustomColorsDialog,
        )

        path = self.preferences_path
        dialog = CustomColorsDialog(
            self._view, title=CUSTOM_TEXTILES_TITLE, prefix="tex", entries=self.custom_textiles_entries(),
            on_change=lambda entries: save_custom_textiles(entries, path),
            new_name=CUSTOM_TEXTILES_NEW_NAME, empty_text=CUSTOM_TEXTILES_EMPTY,
            help_text=CUSTOM_TEXTILES_HELP,
        )
        dialog.exec()
        self._view.set_log_message(f"Tecidos personalizados: {len(dialog.entries())} tecido(s).")

    # ------------------------------------------------------------ Separations
    def apply_separations_state(self, order: list[str], snapshots: dict) -> None:
        """Aplicador do undo das operações de Separations / Generate Black."""
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

    def _require_separations(self, title: str) -> list | None:
        channels = list(self.project_state.channels)
        if not channels or self.project_state.active_document is None:
            QMessageBox.warning(self._view, title, "Abra uma arte primeiro.")
            return None
        return channels

    def _image_lab(self) -> ops.ImageLab | None:
        doc = self.project_state.active_document
        if doc is None:
            return None
        key = f"{doc.id}:{doc.width}x{doc.height}"
        if self._lab_cache is None or self._lab_cache[0] != key:
            self._lab_cache = (key, ops.ImageLab.from_rgb(doc.array, doc.alpha))
        return self._lab_cache[1]

    def enhance_red_orange(self) -> None:
        channels = self._require_separations("Realçar vermelho/laranja")
        if channels is None:
            return
        edit = ops.enhance_red_orange(channels, self._image_lab())
        self._commit_edit("Realçar vermelho/laranja", edit, "Não há separação vermelha para realçar.")

    def generate_brown(self) -> None:
        channels = self._require_separations("Gerar marrom")
        if channels is None:
            return
        self._commit_edit("Gerar marrom", ops.generate_brown(channels, self._image_lab()), "Sem dados de marrom.")

    def _merge(self, family: str, title: str) -> None:
        channels = self._require_separations(title)
        if channels is None:
            return
        edit = ops.merge_family(channels, family)  # type: ignore[arg-type]
        labels = {"gray": "cinza", "purple": "roxo", "turquoise": "turquesa"}
        self._commit_edit(title, edit, f"Não há separação {labels.get(family, family)} para fundir.")

    def merge_gray(self) -> None:
        self._merge("gray", "Fundir cinza")

    def merge_purple(self) -> None:
        self._merge("purple", "Fundir roxo")

    def merge_turquoise(self) -> None:
        self._merge("turquoise", "Fundir turquesa")

    def create_underbase(self) -> None:
        """Create Underbase / botão Underbase...: 'Live Underbase Properties'; cria ou REFAZ a Underbase."""
        channels = self._require_separations("Criar base branca")
        if channels is None:
            return
        doc = self.project_state.active_document
        self.sync_underbase_link()
        existing = find_underbase(channels)
        if doc.id not in self._engine_underbase:
            self._engine_underbase[doc.id] = ops.source_mask(existing).copy() if existing is not None else None
        link = self._underbase_links.get(doc.id)
        current = link if link is not None and not link.detached else None
        dialog = LiveUnderbaseDialog(
            self._view, channels,
            settings=current.settings if current else None,
            mode=current.mode if current else "live",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        settings, mode = dialog.settings(), dialog.result_mode()
        mask = live_underbase_mask(
            channels, settings, dpi=self._document_dpi(), alpha=doc.alpha, cap=self._engine_underbase[doc.id]
        )
        if mask is None:
            QMessageBox.information(
                self._view, "Criar base branca", "Não há dados de separação para gerar a base branca."
            )
            return
        if existing is not None:
            underbase = clone_channel(existing)
            underbase.set_mask(mask)
            updated = [underbase if ch.id == existing.id else ch for ch in channels]
        else:
            underbase = ChannelInfo.create("Base branca", (255, 255, 255), mask=mask, channel_id=str(uuid.uuid4()),
                                           key="underbase", export_name="UNDERBASE", role="underbase")
            updated = [underbase, *channels]
        modo = "Dinâmica" if mode == "live" else "Fixa"
        acao = "atualizada" if existing else "criada"
        edit = ops.diff_edit(
            channels, updated,
            f"Base branca {modo.lower()} {acao}: recuo {settings.choke_pt:.2f} pt, "
            f"{settings.style}, cobertura {ops.coverage(underbase):.1%}.",
        )
        if not self._commit_edit("Criar base branca", edit, "Base branca inalterada."):
            return
        stack = self._core.undo_service.stack
        state_channels = list(self.project_state.channels)
        self._underbase_links[doc.id] = _UnderbaseLink(
            settings=settings,
            mode=mode,
            command=stack.command(stack.index() - 1) if stack.index() > 0 else None,
            checksum=_mask_checksum(find_underbase(state_channels)),
            signature=_separations_signature(state_channels),
            epoch=self._undo_epoch,
        )

    def _document_dpi(self) -> float:
        doc = self.project_state.active_document
        return float(doc.dpi[0]) if doc is not None and doc.dpi and doc.dpi[0] else 300.0

    def _on_undo_index_changed(self, _index: int) -> None:
        self._undo_epoch += 1

    def schedule_underbase_sync(self) -> None:
        """Separações mudaram: a Live Underbase é refeita (com o laço de eventos livre)."""
        link = self._live_link()
        if link is not None:
            self._live_timer.start()

    def _live_link(self) -> _UnderbaseLink | None:
        doc = self.project_state.active_document
        link = self._underbase_links.get(doc.id) if doc is not None else None
        return link if link is not None and not link.detached else None

    def _link_command_done(self, link: _UnderbaseLink) -> bool:
        """False quando o Create Underbase do vínculo foi desfeito (Undo)."""
        stack = self._core.undo_service.stack
        for i in range(stack.count()):
            if stack.command(i) is link.command:
                return i < stack.index()
        return True

    def sync_underbase_link(self) -> None:
        """Mantém o vínculo da Underbase: Live recalcula quando as separações mudam; Static só acompanha.

        Uma Underbase trocada fora do undo (documento restaurado) desfaz o vínculo.
        """
        link = self._live_link()
        if link is None:
            return
        channels = list(self.project_state.channels)
        underbase = find_underbase(channels)
        checksum = _mask_checksum(underbase)
        if self._undo_epoch == link.epoch:
            if checksum != link.checksum:
                link.detached = True
            return
        link.epoch = self._undo_epoch
        if self._link_command_done(link) and link.mode == "live" and underbase is not None:
            signature = _separations_signature(channels)
            if signature != link.signature or checksum != link.checksum:
                link.signature = signature
                doc = self.project_state.active_document
                mask = live_underbase_mask(
                    channels, link.settings, dpi=self._document_dpi(), alpha=doc.alpha,
                    cap=self._engine_underbase.get(doc.id),
                )
                if mask is not None:
                    underbase.set_mask(mask)
                    checksum = _mask_checksum(underbase)
                    link.checksum = checksum
                    self._view.channels_dock.update_channel(underbase)
                    self._core.channels.refresh_preview(incremental=False)
                    self._view.set_log_message(
                        f"Base branca dinâmica atualizada: cobertura {ops.coverage(underbase):.1%}."
                    )
        link.checksum = checksum

    def underbase_mode(self) -> UnderbaseMode | None:
        """'live'/'static' da Underbase criada pela janela Live Underbase Properties (None sem vínculo)."""
        link = self._live_link()
        return link.mode if link is not None else None

    def press_fit(self) -> None:
        channels = self._require_separations("Encaixe na mesa")
        if channels is None:
            return
        if len(channels) < 2:
            QMessageBox.information(self._view, "Encaixe na mesa", "Só há uma separação — nada para encaixar.")
            return
        from packages.image.textile import ground_color_for_state

        dialog = PressFitDialog(
            self._view, channels, screens=self.press_size, ground_rgb=ground_color_for_state(self.project_state)
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edit = ops.press_fit_by_screens(channels, dialog.assignment(), prefer=dialog.prefer())
        self._commit_edit(
            "Encaixe na mesa", edit, f"As {len(channels)} separações já cabem na mesa."
        )

    def _adjust_saturation_range(self, title: str, target_ids: list[str], subtitle: str) -> None:
        """Diálogo SS4 'Adjust by Saturation Range' com a linha de caixas por separação, preview e undo.

        As caixas começam marcadas em ``target_ids``; só as marcadas ao aceitar são alteradas.
        """
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

    def adjust_separations(self) -> None:
        """Adjust Separations... (Ctrl+J): caixas marcadas conforme as Active Separations."""
        if self._require_separations("Ajustar separações") is None:
            return
        ids = self.active_separation_ids()
        self._adjust_saturation_range("Ajustar separações", ids, "")

    def auto_adjust(self) -> None:
        channels = self._require_separations("Ajuste automático")
        if channels is None:
            return
        edit = ops.auto_adjust(channels, self.active_separation_ids())
        self._commit_edit("Ajuste automático", edit, "Nenhuma separação de cor ativa para ajustar.")

    def _generate_black_variant(self, variant: str) -> None:
        """Generate Black: o '...' abre o seletor de arquivo (o arquivo aberto vem pré-selecionado)."""
        variant_pt = {"skeletal": "Esquelético", "detailed": "Detalhado", "sharper": "Mais nítido"}
        title = f"Gerar preto — {variant_pt.get(variant, variant.capitalize())}"
        channels = self._require_separations(title)
        if channels is None:
            return
        doc = self.project_state.active_document
        path, _ = QFileDialog.getOpenFileName(self._view, title, doc.path or "", BLACK_FILE_FILTER)
        if not path:
            return
        lab = self._black_source_lab(path)
        if lab is None:
            return
        edit = ops.generate_black(channels, lab, variant)  # type: ignore[arg-type]
        self._commit_edit(title, edit, "Sem sombras para gerar a separação de preto.")

    def _black_source_lab(self, path: str) -> ops.ImageLab | None:
        """Lab do arquivo escolhido no tamanho do documento (o próprio documento quando é o mesmo arquivo)."""
        from packages.image.io import load_image

        doc = self.project_state.active_document
        if doc.path and Path(path).resolve() == Path(doc.path).resolve():
            return self._image_lab()
        try:
            source = load_image(path)
        except Exception as exc:  # noqa: BLE001 — arquivo ilegível: avisa e não altera nada
            QMessageBox.warning(self._view, "Gerar preto", f"Não foi possível abrir o arquivo:\n{exc}")
            return None
        rgb, alpha = np.asarray(source.array), source.alpha
        if rgb.shape[:2] != (doc.height, doc.width):
            rgb = cv2.resize(rgb, (doc.width, doc.height), interpolation=cv2.INTER_AREA)
            if alpha is not None:
                alpha = cv2.resize(np.asarray(alpha, dtype=np.float32), (doc.width, doc.height),
                                   interpolation=cv2.INTER_LINEAR)
        return ops.ImageLab.from_rgb(rgb, alpha)

    def generate_black_skeletal(self) -> None:
        self._generate_black_variant("skeletal")

    def generate_black_detailed(self) -> None:
        self._generate_black_variant("detailed")

    def generate_black_sharper(self) -> None:
        self._generate_black_variant("sharper")

    def generate_black(self) -> None:
        """Key plate do motor FAV8 (fluxo antigo, fora dos menus do SS4)."""
        if self.project_state.active_document is None:
            QMessageBox.warning(self._view, "Gerar preto", "Abra uma arte primeiro.")
            return
        self._view.params_dock.key_plate_enabled.setChecked(True)
        params = self._ss4_params()
        params["key_plate_enabled"] = True
        self._view.set_log_message("Gerar preto — chapa chave FAV8…")
        self._core.separate_channels(params, prompt_engine=False)

    # ------------------------------------------------------------ Proof Positive / View
    def set_separation_visible(self, channel_id: str, visible: bool) -> None:
        self._core.set_channel_visible(channel_id, visible)
        self._view.channels_dock.set_channel_checked(channel_id, visible)

    def hide_all_separations(self) -> None:
        self._core.channels.set_all_channels_visible(False)

    def show_all_separations(self) -> None:
        self._core.channels.set_all_channels_visible(True)

    def toggle_textile_color(self) -> None:
        self.set_show_textile_color(not self.project_state.show_textile_color)

    def set_show_textile_color(self, on: bool) -> None:
        self.project_state.show_textile_color = bool(on)
        self._core.channels.refresh_preview(incremental=False)
        self._sync_view()

    def set_proof_view(self) -> None:
        self._core.on_preview_display_mode_changed("proof")

    def set_ink_view(self) -> None:
        self._core.on_preview_display_mode_changed("ink")

    def set_film_view(self) -> None:
        self._core.on_preview_display_mode_changed("film")

    def _documents(self):
        return getattr(self._view, "documents", None)

    def _active_view(self):
        documents = self._documents()
        return documents.active_view() if documents is not None else self._view.canvas.active_view

    def _zoom_active(self, command: str) -> None:
        """Comandos de zoom do menu View agem na janela ativa (Drag all windows leva as outras)."""
        view = self._active_view()
        getattr(view, command)()
        documents = self._documents()
        if documents is not None:
            documents.sync_from(view)

    def zoom_in(self) -> None:
        self._zoom_active("zoom_in")

    def zoom_out(self) -> None:
        self._zoom_active("zoom_out")

    def zoom_fill_window(self) -> None:
        self._zoom_active("fill_window")

    def fit_on_screen(self) -> None:
        self._zoom_active("fit_to_window")

    def actual_pixels(self) -> None:
        self._zoom_active("actual_pixels")

    def match_zoom(self) -> None:
        """View > Match Zoom: aplica o zoom (e o centro) da janela ativa a todas as janelas."""
        active = self._active_view()
        documents = self._documents()
        count = documents.match_zoom(active) if documents is not None else 1
        self._view.set_log_message(
            f"Igualar zoom: {active.transform().m11():.0%} aplicado a {count} janela(s)."
        )

    def document_properties(self, channel_id: str | None = None) -> None:
        """View > Document Properties...; com ``channel_id`` (clique direito na caixa de cor) cita a separação."""
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

    # ------------------------------------------------------------ Window
    def toggle_lock_toolbars(self) -> None:
        self.set_toolbars_locked(not self._toolbars_locked)

    def set_toolbars_locked(self, locked: bool) -> None:
        self._toolbars_locked = bool(locked)
        apply = getattr(self._view, "set_toolbars_locked", None)
        if callable(apply):
            apply(self._toolbars_locked)

    @property
    def toolbars_locked(self) -> bool:
        return self._toolbars_locked

    def focus_vue_rite(self) -> None:
        documents = self._documents()
        if documents is not None and not documents.main_window.isHidden():
            documents.activate(documents.main_window)
        self._view.canvas.setFocus()

    def open_in_new_window(self, kind: str = PROOF_VIEW) -> None:
        """Window > New Window: nova janela com o Proof Positive ou com uma separação."""
        if self.project_state.active_document is None:
            QMessageBox.warning(self._view, "Nova janela", "Abra uma arte primeiro.")
            return
        window = self._view.documents.open_window(kind)
        if window is None:
            QMessageBox.information(self._view, "Nova janela", "Ainda não há nada para mostrar em nova janela.")
            return
        self._view.set_log_message(f"Nova janela: {window.windowTitle()}")

    def open_selected_in_new_window(self) -> None:
        """Menu de contexto da separação: 'Open in a new window'."""
        channel = self._target_channel("Abrir em nova janela")
        if channel is not None:
            self.open_in_new_window(channel.id)

    def cascade_windows(self) -> None:
        self._view.documents.cascadeSubWindows()

    def tile_windows(self) -> None:
        self._view.documents.tileSubWindows()

    # ------------------------------------------------------------ Support
    def open_preferences(self) -> None:
        """Support > Preferences...: Default Separation View, Undo Limit e Default Press Size."""
        dialog = PreferencesDialog(
            self._view, default_view=self.default_view, undo_limit=self.undo_limit, press_size=self.press_size
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.default_view = dialog.default_view()
        self.undo_limit = dialog.undo_limit()
        self.press_size = dialog.press_size()
        self._core.undo_service.set_undo_limit(self.undo_limit)
        self._core.on_preview_display_mode_changed(self.default_view)
        self._view.set_log_message(
            f"Preferências: vista {self.default_view}, limite de desfazer {self.undo_limit}, "
            f"telas na mesa {self.press_size}."
        )

    def open_user_guides(self) -> None:
        if not USER_GUIDE.exists():
            QMessageBox.warning(self._view, "Guias do usuário", f"Guia não encontrado:\n{USER_GUIDE}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(USER_GUIDE)))
        self._view.set_log_message(f"Guia do usuário: {USER_GUIDE.name}")

    def show_about(self) -> None:
        from packages.skills.fav8_plus.engine import ENGINE_VERSION

        counts = catalog_summary()
        QMessageBox.about(
            self._view,
            f"Sobre o {APP_NAME}",
            f"{APP_NAME}\n{APP_SUBTITLE}\n\n"
            f"Motor de separação: {ENGINE_VERSION} (Spot Process, preset FAV8+).\n\n"
            f"Ações: {counts.get('shipped', 0)} ativas, "
            f"{counts.get('stub', 0)} em desenvolvimento, {counts.get('planned', 0)} planejadas.",
        )

    # ------------------------------------------------------------ ferramentas
    def tool_move(self) -> None:
        self._core.handle_tool("move")

    def tool_zoom(self) -> None:
        self._core.handle_tool("zoom")
        self._view.set_log_message(
            "Ferramenta Zoom: clique para ampliar; Alt+clique ou botão direito para reduzir."
        )

    def tool_lasso(self) -> None:
        self._view.canvas.set_tool(CanvasTool.LASSO)

    def tool_poly_lasso(self) -> None:
        self._view.canvas.set_tool(CanvasTool.POLY_LASSO)
        self._view.set_log_message(
            "Laço poligonal: clique nos vértices; duplo clique ou Enter para fechar."
        )

    def tool_rect_select(self) -> None:
        self._view.canvas.set_tool(CanvasTool.SELECT)

    def tool_select(self) -> None:
        self.tool_rect_select()

    def tool_saturate(self) -> None:
        self._view.canvas.set_tool(CanvasTool.SATURATE)
        self._view.set_log_message("Encharcar: arraste para escurecer (mais tinta) nas separações ativas.")

    def tool_desaturate(self) -> None:
        self._view.canvas.set_tool(CanvasTool.DESATURATE)
        self._view.set_log_message("Aliviar tinta: arraste para clarear (menos tinta) nas separações ativas.")

    def tool_eraser(self) -> None:
        self._view.canvas.set_tool(CanvasTool.ERASER)
        self._view.set_log_message("Borracha: arraste para apagar tinta das separações ativas.")

    # ------------------------------------------------------------ Tool Options
    def set_brush_hardness(self, percent: int) -> None:
        self.brush_hardness = float(np.clip(percent, 0, 100)) / 100.0

    def set_brush_range(self, value_range: str) -> None:
        raw = str(value_range).strip().lower()
        key = raw if raw in cops.SATURATION_RANGES else raw.split()[0]
        # Aceita chave (low/mid/high) ou rótulo antigo/novo começando por low/mid/high.
        if key in cops.SATURATION_RANGES:
            self.brush_range = key  # type: ignore[assignment]
        elif "baixa" in raw or raw.startswith("low"):
            self.brush_range = "low"
        elif "média" in raw or "media" in raw or raw.startswith("mid"):
            self.brush_range = "mid"
        elif "alta" in raw or raw.startswith("high"):
            self.brush_range = "high"

    # ------------------------------------------------------------ Saturate / Desaturate / Eraser
    def begin_brush_stroke(self, tool: str, x: float, y: float, _alt: bool = False) -> None:
        state = self.project_state
        if not state.channels or state.active_document is None or tool not in _BRUSH_TITLES:
            return
        ids = self.active_separation_ids()
        if not ids:
            self._view.set_log_message("Nenhuma separação ativa: marque uma em Separações ativas.")
            return
        stroke = cops.BrushStroke.start(
            tool,  # type: ignore[arg-type]
            list(state.channels),
            ids,
            diameter=self._view.canvas.active_view.brush_diameter,
            hardness=self.brush_hardness,
            flow=self.brush_flow,
            value_range=self.brush_range,
        )
        self._stroke = stroke
        self._stroke_before = {ch.id: clone_channel(ch) for ch in state.channels if ch.id in stroke.working}
        self._stroke_preview_at = 0.0
        stroke.press(x, y)
        self._flush_stroke(preview=True)

    def continue_brush_stroke(self, x: float, y: float) -> None:
        if self._stroke is None:
            return
        self._stroke.move_to(x, y)
        self._flush_stroke(preview=True)

    def end_brush_stroke(self) -> None:
        stroke, before = self._stroke, self._stroke_before
        self._stroke, self._stroke_before = None, {}
        if stroke is None:
            return
        self._flush_stroke(stroke, preview=False)
        if not stroke.touched:
            return
        channels = list(self.project_state.channels)
        title = _BRUSH_TITLES[stroke.tool]
        edit = ops.SeparationEdit(
            channels,
            changed={cid for cid in stroke.touched if cid in before},
            message=f"{title}: {len(stroke.touched)} separação(ões).",
        )
        before_list = [before.get(ch.id, ch) for ch in channels]
        self._core.undo_service.push(ReplaceSeparationsCommand(title, before_list, edit, self))
        self._view.set_log_message(edit.message)

    def _flush_stroke(self, stroke: cops.BrushStroke | None = None, *, preview: bool) -> None:
        """Copia as máscaras de trabalho do traço para as separações vivas (preview limitado)."""
        stroke = stroke or self._stroke
        if stroke is None:
            return
        now = time.monotonic()
        if preview and now - self._stroke_preview_at < _STROKE_PREVIEW_INTERVAL_S:
            return
        live = {ch.id: ch for ch in self.project_state.channels}
        dirty = stroke.take_dirty()
        for cid, raw in dirty.items():
            if cid in live:
                live[cid].set_mask(raw)
        if preview and dirty:
            self._stroke_preview_at = now
            self._core.channels.refresh_preview(incremental=True)

    # ------------------------------------------------------------ barra superior
    def toggle_drag_all_windows(self) -> None:
        self.set_drag_all_windows(not self._drag_all_windows)

    def set_drag_all_windows(self, on: bool) -> None:
        self._drag_all_windows = bool(on)
        documents = self._documents()
        if documents is not None:
            documents.link_views = self._drag_all_windows
            if self._drag_all_windows:
                documents.sync_from(documents.active_view())

    @property
    def drag_all_windows(self) -> bool:
        return self._drag_all_windows

    def active_separation_ids(self) -> list[str]:
        """Separações marcadas em 'Active Separations' — alvo das ferramentas de edição."""
        return [ch.id for ch in self.project_state.channels if ch.id not in self._inactive_ids]

    def is_separation_active(self, channel_id: str) -> bool:
        return channel_id not in self._inactive_ids

    def set_separation_active(self, channel_id: str, active: bool) -> None:
        if active:
            self._inactive_ids.discard(channel_id)
        else:
            self._inactive_ids.add(channel_id)
        self._sync_view()

    def select_all_active(self) -> None:
        self._inactive_ids.clear()
        self._sync_view()

    def deselect_all_active(self) -> None:
        self._inactive_ids = {ch.id for ch in self.project_state.channels}
        self._sync_view()

    # ------------------------------------------------------------ separação selecionada
    def select_channel(self, channel_id: str | None) -> bool:
        return self._view.channels_dock.select_channel(channel_id)

    def selected_channel_id(self) -> str | None:
        return self._view.channels_dock.selected_channel_id()

    @staticmethod
    def _channel_label(channel) -> str:
        return separation_display_name(channel.name) or channel.id[:8]

    def _target_channel(self, title: str):
        """Separação selecionada na barra; sem seleção, pergunta qual separação."""
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

    def duplicate_channel(self) -> None:
        self.duplicate_selected_channel()

    def adjust_selected_channel(self) -> None:
        """View > Adjust Separation / menu de contexto: 'Adjust by Saturation Range' na separação."""
        channel = self._target_channel("Ajustar separação")
        if channel is not None:
            self._adjust_channel_saturation(channel)

    def adjust_separation(self, channel_id: str) -> None:
        """Duplo clique na miniatura: 'Adjust by Saturation Range' daquela separação."""
        channel = next((ch for ch in self.project_state.channels if ch.id == channel_id), None)
        if channel is not None:
            self.select_channel(channel_id)
            self._adjust_channel_saturation(channel)

    def _adjust_channel_saturation(self, channel) -> None:
        if channel.raw_mask is None:
            QMessageBox.warning(
                self._view, "Ajustar separação", f"\"{channel.name}\" não tem dados para ajustar."
            )
            return
        self._adjust_saturation_range("Ajustar separação", [channel.id], self._channel_label(channel))

    def channels_apply(self) -> None:
        self._core.channels.refresh_preview(incremental=False)

    # ------------------------------------------------------------ densitômetro / impressão
    def toggle_densitometer(self) -> None:
        self._densitometer_enabled = not self._densitometer_enabled
        if not self._densitometer_enabled:
            self._view.set_density_message("off")
        else:
            self._view.set_log_message("Densitômetro ligado — mova o cursor sobre a imagem.")

    def on_result_pixel_probe(self, x: int, y: int) -> None:
        if not self._densitometer_enabled:
            return
        self._core.on_result_pixel_probe(x, y)

    def set_channel_print_enabled(self, channel_id: str, enabled: bool) -> None:
        self._channel_print[channel_id] = enabled
        self._view.set_log_message(f"Impressão {'ligada' if enabled else 'desligada'}: {channel_id[:8]}")

    def show_catalog(self) -> None:
        lines = [
            f"[{a.status.value}] {a.action_id} — {a.label}"
            for a in sorted(SS4_ACTIONS, key=lambda x: x.action_id)
        ]
        QMessageBox.information(self._view, f"Catálogo {APP_NAME_SHORT}", "\n".join(lines))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._core, name)


def catalog_summary() -> dict[str, int]:
    counts = {status.value: 0 for status in ActionStatus}
    for action in SS4_ACTIONS:
        counts[action.status.value] += 1
    return counts
