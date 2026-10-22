from __future__ import annotations

import os
from pathlib import Path


def get_app_data_dir() -> Path:
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    path = Path(appdata) / "ADNY Separador"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
