"""Persistência segura e independente da biblioteca de tintas do usuário."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Mapping

from packages.infra.files.paths import get_app_data_dir
from packages.skills.fav8_plus.ink_library import (
    InkLibrarySnapshot,
    default_ink_library,
)

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}


def _path_lock(path: Path) -> threading.RLock:
    key = str(path.resolve()).casefold()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


class InkLibraryService:
    """Carrega e grava JSON atomicamente em AppData, fora do tune_profile."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (get_app_data_dir() / "ink_library.json")
        self._lock = _path_lock(self.path)

    def load(self) -> InkLibrarySnapshot:
        with self._lock:
            if not self.path.exists():
                snapshot = default_ink_library()
                self._write(snapshot, self.path)
                return snapshot
            return self._read(self.path)

    def save(self, snapshot: InkLibrarySnapshot | Mapping[str, Any]) -> InkLibrarySnapshot:
        validated = (
            snapshot
            if isinstance(snapshot, InkLibrarySnapshot)
            else InkLibrarySnapshot.from_dict(snapshot)
        )
        with self._lock:
            self._write(validated, self.path)
        return validated

    def import_file(self, source: str | Path) -> InkLibrarySnapshot:
        imported = self._read(Path(source))
        return self.save(imported)

    def export_file(self, destination: str | Path) -> Path:
        target = Path(destination)
        with self._lock:
            snapshot = self.load()
            self._write(snapshot, target)
        return target

    def reset(self) -> InkLibrarySnapshot:
        return self.save(default_ink_library())

    @staticmethod
    def _read(path: Path) -> InkLibrarySnapshot:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON de biblioteca malformado em {path}: {exc.msg}.") from exc
        if not isinstance(value, Mapping):
            raise ValueError("A raiz da biblioteca deve ser um objeto JSON.")
        return InkLibrarySnapshot.from_dict(value)

    @staticmethod
    def _write(snapshot: InkLibrarySnapshot, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            snapshot.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            text=True,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
