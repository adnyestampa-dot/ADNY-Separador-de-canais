"""Controles mínimos e explícitos para exportação de filmes FAV8+."""

from __future__ import annotations

from collections.abc import Sequence
from threading import Event

import numpy as np
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from packages.prepress.models import (
    FilmConfig,
    JointCleanupConfig,
    OverprintConfig,
    PrepressConfig,
    ScreenConfig,
    ToneCurveConfig,
    TrapConfig,
    WhiteConfig,
)
from packages.core.models.channel_info import ChannelInfo
from packages.prepress.digital_proof import (
    DIGITAL_PROOF_LABEL,
    DigitalProofCancelled,
    render_digital_proof,
)
from packages.prepress.operations import PrepressPlate


class _ProofSignals(QObject):
    ready = Signal(object)
    failed = Signal(str)


class _ProofTask(QRunnable):
    def __init__(self, render, signals: _ProofSignals) -> None:
        super().__init__()
        self._render = render
        self._signals = signals

    def run(self) -> None:
        try:
            self._signals.ready.emit(self._render())
        except DigitalProofCancelled:
            return
        except Exception as exc:
            self._signals.failed.emit(str(exc))


def _double(minimum: float, maximum: float, value: float, decimals: int = 2) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(decimals)
    widget.setValue(value)
    return widget


class PrepressDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        dpi: float = 300.0,
        channels: Sequence[ChannelInfo] = (),
        initial_config: PrepressConfig | None = None,
        alpha: np.ndarray | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Exportar filmes — Pré-impressão FAV8+")
        self.setMinimumWidth(460)
        self._alpha = None if alpha is None else np.asarray(alpha).copy()
        self._proof_cancel = Event()
        self._proof_signals = _ProofSignals(self)
        self._proof_signals.ready.connect(self._show_proof)
        self._proof_signals.failed.connect(self._show_proof_error)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.dpi = _double(36, 2400, dpi, 0)
        self.margin = _double(0, 100, 12)
        self.cleanup_mode = QComboBox()
        self.cleanup_mode.addItem("Desativada", "off")
        self.cleanup_mode.addItem("Automática por DPI/LPI", "auto")
        self.cleanup_mode.addItem("Override manual", "manual")
        self.cleanup_threshold = _double(0, 1, 0.03, 3)
        self.cleanup_min_area = QSpinBox()
        self.cleanup_min_area.setRange(1, 100_000)
        self.cleanup_min_area.setValue(4)
        self.white_mode = QComboBox()
        for label, value in (
            ("Desativado", "off"),
            ("Underbase", "underbase"),
            ("Top-white", "top_white"),
            ("Underbase + top-white", "both"),
        ):
            self.white_mode.addItem(label, value)
        self.white_policy = QComboBox()
        self.white_policy.addItem("Reutilizar existentes", "reuse_existing")
        self.white_policy.addItem("Substituir existentes", "replace_existing")
        self.white_policy.addItem("Gerar somente ausentes", "generate_if_missing")
        self.choke = _double(0, 5, 0)
        self.trapping = QCheckBox("Ativar spread claro sob escuro")
        self.spread = _double(0, 5, 0.1)
        self.overprint = QCheckBox("Ativar knockout/build-up")
        self.overprint_mode = QComboBox()
        self.overprint_mode.addItem("Knockout", "knockout")
        self.overprint_mode.addItem("Build-up", "build_up")
        self.reach = _double(0, 5, 0)
        self.screen_mode = QComboBox()
        self.screen_mode.addItem("Sem screening", "none")
        self.screen_mode.addItem("AM", "am")
        self.screen_mode.addItem("FM", "fm")
        self.lpi = _double(1, 300, 45, 1)
        self.fm_dot = _double(20, 1000, 180, 0)
        defaults = ScreenConfig()
        self.angle = _double(0, 179.9, defaults.default_angle, 1)
        self.role_angles: dict[str, QDoubleSpinBox] = {}
        for role, value in defaults.angles_by_role.items():
            widget = _double(0, 179.9, value, 1)
            self.role_angles[role] = widget
        self.channel_angle_overrides: dict[str, QCheckBox] = {}
        self.channel_angles: dict[str, QDoubleSpinBox] = {}
        for channel in channels:
            key = channel.key or channel.id
            checkbox = QCheckBox(f"Override de {channel.name} ({key})")
            widget = _double(
                0,
                179.9,
                defaults.angle_for(key, channel.role),
                1,
            )
            widget.setEnabled(False)
            checkbox.toggled.connect(widget.setEnabled)
            self.channel_angle_overrides[key] = checkbox
            self.channel_angles[key] = widget
        # Compatibilidade da automação existente da key.
        self.key_angle = self.channel_angles.get(
            "black", self.role_angles["key"]
        )
        self.key_angle_override = self.channel_angle_overrides.get(
            "black", QCheckBox("Usar override de canal para black")
        )
        if "black" not in self.channel_angles:
            self.key_angle_override.toggled.connect(self.key_angle.setEnabled)
        self.key_angle_label = QLabel()
        self.angle_collisions_label = QLabel()
        self.angle_collisions_label.setWordWrap(True)
        self.tone_curve_enabled = QCheckBox(
            "Aplicar curva tonal (independente do screening)"
        )
        self.min_dot = _double(0, 0.99, 0)
        self.max_dot = _double(0.01, 1, 1)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2_147_483_647)
        self.dot_gain = _double(-0.5, 0.5, 0)
        self.gamma = _double(0.1, 5, 1)

        form.addRow("DPI do filme:", self.dpi)
        form.addRow("Margem (mm):", self.margin)
        form.addRow("Limpeza conjunta:", self.cleanup_mode)
        form.addRow("Threshold da limpeza:", self.cleanup_threshold)
        form.addRow("Área mínima (px):", self.cleanup_min_area)
        form.addRow("Brancos:", self.white_mode)
        form.addRow("Política de brancos:", self.white_policy)
        form.addRow("Choke do branco (mm):", self.choke)
        form.addRow(self.trapping)
        form.addRow("Trap/spread (mm):", self.spread)
        form.addRow(self.overprint)
        form.addRow("Modo de tinta:", self.overprint_mode)
        form.addRow("Overprint reach (mm):", self.reach)
        form.addRow("Screening:", self.screen_mode)
        form.addRow("LPI (AM):", self.lpi)
        form.addRow("Ponto FM (µm):", self.fm_dot)
        form.addRow("Ângulo padrão (graus):", self.angle)
        for role, widget in self.role_angles.items():
            form.addRow(f"Ângulo role {role}:", widget)
        for key, checkbox in self.channel_angle_overrides.items():
            form.addRow(checkbox)
            form.addRow(f"Ângulo canal {key}:", self.channel_angles[key])
        form.addRow(self.key_angle_label)
        form.addRow(self.angle_collisions_label)
        form.addRow(self.tone_curve_enabled)
        form.addRow("Ponto mínimo:", self.min_dot)
        form.addRow("Ponto máximo:", self.max_dot)
        form.addRow("Seed FM:", self.seed)
        form.addRow("Ganho de ponto:", self.dot_gain)
        form.addRow("Gamma da curva:", self.gamma)
        layout.addLayout(form)
        angle_widgets = [
            self.angle,
            *self.role_angles.values(),
            *self.channel_angles.values(),
        ]
        for widget in angle_widgets:
            widget.valueChanged.connect(self._refresh_angle_diagnostics)
        for checkbox in self.channel_angle_overrides.values():
            checkbox.toggled.connect(self._refresh_angle_diagnostics)
        self._channels = tuple(channels)
        if initial_config is not None:
            self._apply_config(initial_config)
        self._refresh_angle_diagnostics()

        self.proof_title = QLabel(DIGITAL_PROOF_LABEL)
        self.proof_title.setStyleSheet("font-weight: bold")
        self.preview_mode = QComboBox()
        for label, value in (
            ("Composite", "composite"),
            ("Chapa individual", "plate"),
            ("Key", "key"),
            ("Underbase", "underbase"),
            ("Top-white", "top_white"),
            ("Mapa de trapping/knockout", "trapping_knockout"),
            ("Retícula (zoom de pixel)", "screening"),
        ):
            self.preview_mode.addItem(label, value)
        self.preview_plate = QComboBox()
        for channel in channels:
            self.preview_plate.addItem(channel.name, channel.key or channel.id)
        self.pixel_zoom = QSpinBox()
        self.pixel_zoom.setRange(1, 32)
        self.pixel_zoom.setValue(8)
        self.preview_button = QPushButton("Atualizar preview")
        self.preview_button.clicked.connect(self.request_preview)
        preview_form = QFormLayout()
        preview_form.addRow("Visualização:", self.preview_mode)
        preview_form.addRow("Chapa:", self.preview_plate)
        preview_form.addRow("Zoom de pixel:", self.pixel_zoom)
        preview_form.addRow(self.preview_button)
        layout.addWidget(self.proof_title)
        layout.addLayout(preview_form)
        self.preview_label = QLabel("Preview ainda não gerado.")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(320, 180)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview_label)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Exportar PDF")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_config(self, config: PrepressConfig) -> None:
        def select(combo: QComboBox, value: str) -> None:
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)

        self.dpi.setValue(config.film.dpi)
        self.margin.setValue(config.film.margin_mm)
        select(self.cleanup_mode, config.joint_cleanup.mode)
        self.cleanup_threshold.setValue(config.joint_cleanup.threshold)
        self.cleanup_min_area.setValue(config.joint_cleanup.min_area_px)
        select(self.white_mode, config.white.mode)
        select(self.white_policy, config.white.policy)
        self.choke.setValue(config.white.choke_mm)
        self.trapping.setChecked(config.trapping.enabled)
        self.spread.setValue(config.trapping.spread_mm)
        self.overprint.setChecked(config.overprint.enabled)
        select(self.overprint_mode, config.overprint.mode)
        self.reach.setValue(config.overprint.reach_mm)
        select(self.screen_mode, config.screening.mode)
        self.lpi.setValue(config.screening.lpi)
        self.fm_dot.setValue(config.screening.fm_dot_um)
        self.angle.setValue(config.screening.default_angle)
        for role, widget in self.role_angles.items():
            widget.setValue(config.screening.angles_by_role.get(role, widget.value()))
        for key, angle in config.screening.angles_by_channel.items():
            if key in self.channel_angles:
                self.channel_angle_overrides[key].setChecked(True)
                self.channel_angles[key].setValue(angle)
        self.seed.setValue(config.screening.seed)
        self.tone_curve_enabled.setChecked(config.tone_curve.enabled)
        self.gamma.setValue(config.tone_curve.gamma)
        self.dot_gain.setValue(config.tone_curve.gain)
        self.min_dot.setValue(config.tone_curve.min_value)
        self.max_dot.setValue(config.tone_curve.max_value)

    def request_preview(self) -> None:
        """Gera uma prova reduzida fora da thread da UI."""
        self._proof_cancel.set()
        cancel = Event()
        self._proof_cancel = cancel
        plates = tuple(
            PrepressPlate(
                key=channel.key or channel.id,
                label=channel.name,
                color_rgb=channel.color_rgb,
                mask=np.asarray(channel.mask, dtype=np.float32).copy(),
                role=channel.role,
                export_name=channel.export_name or channel.name,
            )
            for channel in self._channels
            if channel.visible and channel.mask is not None
        )
        config = self.config()
        mode = self.preview_mode.currentData()
        selected = self.preview_plate.currentData()
        alpha = None if self._alpha is None else self._alpha.copy()
        zoom = self.pixel_zoom.value()
        self.preview_button.setEnabled(False)
        self.preview_label.setText("Gerando preview…")

        def render():
            return render_digital_proof(
                plates,
                config,
                dpi=config.film.dpi,
                alpha=alpha,
                mode=mode,
                selected_plate=selected,
                max_size=(1000, 700),
                pixel_zoom=zoom,
                cancelled=cancel.is_set,
            )

        QThreadPool.globalInstance().start(_ProofTask(render, self._proof_signals))

    def _show_proof(self, proof) -> None:
        if self._proof_cancel.is_set():
            return
        self.preview_button.setEnabled(True)
        self.preview_label.setText("")
        self.preview_label.setPixmap(QPixmap.fromImage(ImageQt(proof.image)))

    def _show_proof_error(self, message: str) -> None:
        self.preview_button.setEnabled(True)
        self.preview_label.setText(f"Falha no preview: {message}")

    def reject(self) -> None:
        self._proof_cancel.set()
        super().reject()

    def closeEvent(self, event) -> None:
        self._proof_cancel.set()
        super().closeEvent(event)

    def config(self) -> PrepressConfig:
        angles_by_role = {
            role: widget.value() for role, widget in self.role_angles.items()
        }
        angles_by_channel = {
            key: self.channel_angles[key].value()
            for key, checkbox in self.channel_angle_overrides.items()
            if checkbox.isChecked()
        }
        return PrepressConfig(
            enabled=True,
            joint_cleanup=JointCleanupConfig(
                mode=self.cleanup_mode.currentData(),
                threshold=self.cleanup_threshold.value(),
                min_area_px=self.cleanup_min_area.value(),
            ),
            white=WhiteConfig(
                mode=self.white_mode.currentData(),
                policy=self.white_policy.currentData(),
                choke_mm=self.choke.value(),
            ),
            trapping=TrapConfig(
                enabled=self.trapping.isChecked(),
                spread_mm=self.spread.value(),
            ),
            overprint=OverprintConfig(
                enabled=self.overprint.isChecked(),
                mode=self.overprint_mode.currentData(),
                reach_mm=self.reach.value(),
            ),
            screening=ScreenConfig(
                mode=self.screen_mode.currentData(),
                lpi=self.lpi.value(),
                fm_dot_um=self.fm_dot.value(),
                default_angle=self.angle.value(),
                angles_by_role=angles_by_role,
                angles_by_channel=angles_by_channel,
                seed=self.seed.value(),
            ),
            tone_curve=ToneCurveConfig(
                enabled=self.tone_curve_enabled.isChecked(),
                gamma=self.gamma.value(),
                gain=self.dot_gain.value(),
                min_value=self.min_dot.value(),
                max_value=self.max_dot.value(),
            ),
            film=FilmConfig(dpi=self.dpi.value(), margin_mm=self.margin.value()),
        )

    def _refresh_angle_diagnostics(self) -> None:
        config = self.config().screening
        effective: list[tuple[str, str, float]] = []
        if self._channels:
            for channel in self._channels:
                key = channel.key or channel.id
                effective.append(
                    (key, channel.role, config.angle_for(key, channel.role))
                )
        else:
            effective.append(("black", "key", config.angle_for("black", "key")))
        self.key_angle_label.setText(
            "Ângulos efetivos: "
            + ", ".join(
                f"{key}={angle:.1f}° (role={role})"
                for key, role, angle in effective
            )
        )
        collisions: list[str] = []
        for index, first in enumerate(effective):
            for second in effective[index + 1 :]:
                if abs(first[2] - second[2]) < 1e-9:
                    collisions.append(f"{first[0]}/{second[0]} em {first[2]:.1f}°")
        self.angle_collisions_label.setText(
            "Aviso: colisões de ângulo: " + ", ".join(collisions)
            if collisions
            else "Sem colisões de ângulo."
        )
