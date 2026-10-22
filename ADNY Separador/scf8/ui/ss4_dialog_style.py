"""Visual das janelas escuras do SS4 (título centralizado, botões em pílula, '?')."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QWidget


def dialog_qss(object_name: str) -> str:
    d = f"QDialog#{object_name}"
    return f"""
{d} {{ background: #1e1e1e; }}
{d} QLabel {{ color: #e6e6e6; }}
{d} QLabel#ss4_dialog_title {{ font-size: 15px; padding: 2px 0 4px 0; }}
{d} QFrame#ss4_panel {{ background: #2b2b2b; border-radius: 6px; }}
{d} QSpinBox, {d} QDoubleSpinBox {{ background: #ffffff; color: #000000; min-width: 52px; }}
{d} QComboBox {{ background: #ffffff; color: #000000; min-width: 70px; }}
{d} QPushButton#ss4_help {{ color: #9a9a9a; border: 2px solid #4a4a4a; border-radius: 13px;
  min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; font-weight: bold; }}
{d} QPushButton#pill_red {{ color: #f0f0f0; background: #1e1e1e; border: 2px solid #e02a2a;
  border-radius: 12px; padding: 3px 14px; }}
{d} QPushButton#pill_green_outline {{ color: #f0f0f0; background: #1e1e1e; border: 2px solid #157a1f;
  border-radius: 12px; padding: 3px 14px; }}
{d} QPushButton#pill_green {{ color: #f0f0f0; background: #157a1f; border: 2px solid #157a1f;
  border-radius: 12px; padding: 3px 14px; }}
"""


def title_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("ss4_dialog_title")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def pill_button(text: str, style: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(f"pill_{style}")
    return button


def help_button(parent: QWidget, title: str, text: str) -> QPushButton:
    button = QPushButton("?")
    button.setObjectName("ss4_help")
    button.setToolTip("Ajuda")
    button.clicked.connect(lambda: QMessageBox.information(parent, title, text))
    return button
