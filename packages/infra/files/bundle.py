"""Caminhos de recursos para desenvolvimento e app empacotado (PyInstaller)."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """Raiz do projeto (dev) ou pasta do executável (instalado)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def bundle_root() -> Path:
    """Raiz dos dados empacotados (_MEIPASS) ou do projeto em dev."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", project_root()))
    return project_root()


def resource_path(*parts: str) -> Path:
    """Arquivo ou pasta de recurso relativo ao bundle."""
    return bundle_root().joinpath(*parts)


def scripts_dir() -> Path:
    """Scripts de instalação/manutenção (ao lado do .exe quando instalado)."""
    return project_root() / "scripts"
