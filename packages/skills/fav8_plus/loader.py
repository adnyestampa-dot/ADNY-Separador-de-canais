from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from packages.infra.files.bundle import resource_path

TUNE_PROFILE_PATH = resource_path("packages", "skills", "fav8_plus", "tune_profile.json")


def fav8_plus_engine_available() -> bool:
    return TUNE_PROFILE_PATH.is_file()


def fav8_plus_missing_message() -> str:
    if not TUNE_PROFILE_PATH.is_file():
        return f"Perfil FAV8+ não encontrado: {TUNE_PROFILE_PATH}"
    return "Motor FAV8+ indisponível."


@lru_cache(maxsize=1)
def tune_profile_path() -> Path:
    return TUNE_PROFILE_PATH
