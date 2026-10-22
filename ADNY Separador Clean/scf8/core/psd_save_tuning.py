"""Ajustes aplicados só na hora de salvar o PSD (não alteram a UI nem o motor).

Referência do usuário: Photoshop > Aplicar Imagem > Divisão 100% em BASE e
Branco Brilho (1× cada).

NOTA TÉCNICA:
  Divisão com origem = destino no Photoshop vira (quase) branco uniforme e
  apaga o detalhe da chapa — não reproduz o “aliviar carregado” útil.
  Neste teste usamos redução de meios-tons que preserva 0% e 100%:
      máscara' = máscara²
  (mesmo espírito de aliviar densidade sem o corte bruto do “Aliviar tinta”).

REVERTER:
  1) Ponha APPLY_DIVISION_ON_PSD_SAVE = False
  2) Reinicie o app
  3) Salve de novo — PSD sem este ajuste
"""

from __future__ import annotations

import numpy as np

from scf8.core.naming import separation_display_name

# ---------------------------------------------------------------------------
# INTERRUPTOR — False desliga o ajuste no salvamento do PSD.
# ---------------------------------------------------------------------------
APPLY_DIVISION_ON_PSD_SAVE = True

DIVISION_TARGET_LABELS = frozenset({"BASE", "Branco Brilho"})


def is_psd_division_target(channel_name: str | None, *, role: str = "", key: str = "") -> bool:
    label = separation_display_name(channel_name)
    if label in DIVISION_TARGET_LABELS:
        return True
    role_l = (role or "").lower()
    if role_l in {"underbase", "highlight"}:
        return True
    key_l = (key or "").lower().replace(" ", "_")
    return key_l in {"underbase", "top_white", "topwhite"}


def photoshop_apply_image_divide_self(mask: np.ndarray) -> np.ndarray:
    """Reduz densidade dos meios-tons (teste do fluxo Aplicar Imagem / Divisão).

    máscara' = máscara² — preserva vazio (0) e sólido (1), alivia o “carregado”.
    """
    m = np.clip(np.asarray(mask, dtype=np.float32), 0.0, 1.0)
    return np.square(m, dtype=np.float32)
