"""Bibliotecas das janelas Custom Inks e Custom Textiles.

Tintas custom vivem na biblioteca de tintas do app (``InkLibraryService``) com id ``custom:*``;
as tintas padrão ficam intactas. Tecidos custom ficam nas preferências do clone (INI).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtCore import QSettings

from packages.core.services.ink_library_service import InkLibraryService
from packages.skills.fav8_plus.ink_library import InkDefinition, InkLibrarySnapshot
from scf8.core.color_models import rgb_to_lab

ColorEntry = tuple[str, tuple[int, int, int]]

CUSTOM_INK_PREFIX = "custom:"
DEFAULT_TEXTILES: tuple[ColorEntry, ...] = (("Black", (20, 20, 20)), ("White", (240, 240, 240)))
_TEXTILE_GROUP = "custom_textiles"


def _rgb(values) -> tuple[int, int, int]:
    return tuple(int(max(0, min(255, round(float(v))))) for v in values)  # type: ignore[return-value]


# ------------------------------------------------------------------ Custom Inks

def load_custom_inks(service: InkLibraryService) -> list[ColorEntry]:
    return [(ink.nome, _rgb(ink.display_rgb)) for ink in service.load().inks if ink.id.startswith(CUSTOM_INK_PREFIX)]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:48] or "ink"


def save_custom_inks(service: InkLibraryService, entries: list[ColorEntry]) -> InkLibrarySnapshot:
    snapshot = service.load()
    kept = [ink for ink in snapshot.inks if not ink.id.startswith(CUSTOM_INK_PREFIX)]
    keys = {ink.key for ink in kept}
    custom: list[InkDefinition] = []
    for name, rgb in entries:
        base = f"custom_{_slug(name)}"
        key, n = base, 2
        while key in keys:
            key, n = f"{base}_{n}", n + 1
        keys.add(key)
        rgb = _rgb(rgb)
        lab = tuple(round(v, 6) for v in rgb_to_lab(rgb))
        custom.append(InkDefinition(
            id=f"{CUSTOM_INK_PREFIX}{key}",
            nome=name.strip() or "Custom Ink",
            lab_reference=lab,
            display_rgb=rgb,
            role="chromatic",
            metadados={"key": key, "export_name": (name.strip() or "Custom Ink").upper(), "origem": "Custom Inks"},
        ))
    return service.save(InkLibrarySnapshot(version=snapshot.version, inks=tuple(kept + custom)))


# ------------------------------------------------------------------ Custom Textiles

def _settings(path: Path | str) -> QSettings:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return QSettings(str(path), QSettings.Format.IniFormat)


def load_custom_textiles(path: Path | str) -> list[ColorEntry]:
    raw = _settings(path).value(f"{_TEXTILE_GROUP}/items", None)
    if raw is None:
        return list(DEFAULT_TEXTILES)
    try:
        items = json.loads(str(raw))
        return [(str(item["name"]), _rgb(item["rgb"])) for item in items]
    except (ValueError, TypeError, KeyError):
        return list(DEFAULT_TEXTILES)


def save_custom_textiles(entries: list[ColorEntry], path: Path | str) -> None:
    store = _settings(path)
    store.setValue(f"{_TEXTILE_GROUP}/items",
                   json.dumps([{"name": name, "rgb": list(_rgb(rgb))} for name, rgb in entries]))
    store.sync()
