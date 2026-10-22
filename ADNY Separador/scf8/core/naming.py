from __future__ import annotations

import re

# Prefixo de ordem de prensa do motor: "#2 Red 032" → "Red 032".
_PLATE_PREFIX = re.compile(r"^#\d+\s+")
# Código Pantone/ref. no fim: "Red 032", "Gray C8", "Marrom 470".
_TRAILING_CODE = re.compile(r"\s+((?:\d{2,4}|[A-Za-z]\d+))\s*$")
_COPY_SUFFIX = re.compile(r"\s+copy\s*$", re.IGNORECASE)

# Nomes especiais (estamparia BR) — chave em minúsculas.
_SPECIAL: dict[str, str] = {
    "underbase": "BASE",
    "base branca": "BASE",
    "base": "BASE",
    "top white": "Branco Brilho",
    "branco brilho": "Branco Brilho",
}

# Família de cor (inglês/pt) → substantivo pt-BR da tinta (não adjetivo).
_COLOR_WORDS: dict[str, str] = {
    "red": "Vermelho",
    "vermelho": "Vermelho",
    "blue": "Azul",
    "azul": "Azul",
    "gold": "Ouro",
    "dourado": "Ouro",
    "ouro": "Ouro",
    "purple": "Roxo",
    "roxo": "Roxo",
    "violet": "Violeta",
    "violeta": "Violeta",
    "green": "Verde",
    "verde": "Verde",
    "turquoise": "Turquesa",
    "turquesa": "Turquesa",
    "gray": "Cinza",
    "grey": "Cinza",
    "cinza": "Cinza",
    "brown": "Marrom",
    "marrom": "Marrom",
    "black": "Preto",
    "preto": "Preto",
    "white": "Branco",
    "branco": "Branco",
}


def _translate_plate(text: str, *, keep_code: bool) -> str:
    key = text.lower()
    if key in _SPECIAL:
        return _SPECIAL[key]

    code_match = _TRAILING_CODE.search(text)
    code = code_match.group(1) if code_match else ""
    without_code = _TRAILING_CODE.sub("", text).strip() or text
    word = without_code.split()[0].lower() if without_code else ""
    color = _COLOR_WORDS.get(word) or without_code
    if keep_code and code:
        return f"{color} {code}"
    return color


def separation_display_name(name: str | None) -> str:
    """Nome na UI (pt-BR): '#2 Red 032' → 'Vermelho'; Underbase → BASE; Top White → Branco Brilho."""
    raw = (name or "").strip()
    if not raw:
        return ""

    text = _PLATE_PREFIX.sub("", raw).strip()
    is_copy = bool(_COPY_SUFFIX.search(text))
    if is_copy:
        text = _COPY_SUFFIX.sub("", text).strip()

    label = _translate_plate(text, keep_code=False)
    if is_copy:
        return f"{label} (cópia)"
    return label


def separation_psd_name(name: str | None) -> str:
    """Nome do canal no PSD (pt-BR, só o nome): '#2 Red 032' → 'Vermelho'."""
    return separation_display_name(name)
