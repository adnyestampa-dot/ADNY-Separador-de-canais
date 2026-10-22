"""Leitura do perfil Loop v2 legado.

O motor aplica os overrides durante a construção de cada instância; este módulo
não modifica classes, módulos ou paleta globais.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

import numpy as np

from packages.skills.fav8_plus.loader import tune_profile_path

PROFILE_SCHEMA_VERSION = 1
_REQUIRED_SECTIONS = ("engine", "channels", "calibration")


def profile_hash(profile: dict[str, Any]) -> str:
    payload = {key: value for key, value in profile.items() if key != "profile_hash"}
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_tune_profile(profile: Any) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise ValueError("Perfil Loop v2 deve ser um objeto JSON.")
    if profile.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version incompatível: esperado {PROFILE_SCHEMA_VERSION}, "
            f"recebido {profile.get('schema_version')!r}."
        )
    version = profile.get("profile_version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("profile_version deve ser uma string não vazia.")
    for section in _REQUIRED_SECTIONS:
        if not isinstance(profile.get(section), dict):
            raise ValueError(f"profile.{section} deve ser um objeto.")
    actual_hash = profile_hash(profile)
    expected_hash = profile.get("profile_hash")
    if expected_hash is not None and expected_hash != actual_hash:
        raise ValueError("profile_hash declarado não confere com o conteúdo do perfil.")
    profile = dict(profile)
    profile["profile_hash"] = actual_hash
    return profile


def load_tune_profile(path: Path | None = None) -> dict[str, Any]:
    profile_path = path or tune_profile_path()
    if not profile_path.is_file():
        raise FileNotFoundError(f"Perfil Loop v2 não encontrado: {profile_path}")
    return validate_tune_profile(json.loads(profile_path.read_text(encoding="utf-8")))


def apply_calibrations(
    channels: dict[str, np.ndarray],
    profile: dict[str, Any],
    alpha: np.ndarray,
) -> dict[str, np.ndarray]:
    cal = profile.get("calibration", {})
    out = {
        name: np.minimum(np.clip(mask, 0.0, 1.0), alpha).astype(np.float32)
        for name, mask in channels.items()
    }
    if not cal:
        return out
    for name, mask in channels.items():
        c = cal.get(name, {})
        if not c:
            continue
        scale = float(c.get("scale", 1.0))
        offset = float(c.get("offset", 0.0))
        relative = np.divide(
            mask.astype(np.float32),
            alpha,
            out=np.zeros_like(mask, dtype=np.float32),
            where=alpha > 1e-8,
        )
        out[name] = np.minimum(
            np.clip(relative * scale + offset, 0.0, 1.0) * alpha,
            alpha,
        ).astype(np.float32)
    return out
