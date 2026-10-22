"""Operações SS4 pós-separação (menu Separations e Generate Black), fora do motor.

Todas as funções são puras: recebem a lista de separações (``ChannelInfo``) e devolvem um
``SeparationEdit`` com a lista nova. Separações alteradas são objetos novos; as intactas são
as mesmas instâncias — assim o presenter grava no undo só o que mudou.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

import cv2
import numpy as np

from packages.core.models.channel_info import ChannelInfo
from packages.core.services.channel_ops import clone_channel
from scf8.core.naming import separation_display_name

BlackVariant = Literal["skeletal", "detailed", "sharper"]
MergeFamily = Literal["gray", "purple", "turquoise"]

WHITE_ROLES = {"underbase", "highlight"}
AUTO_ADJUST_HIGH = 10
AUTO_ADJUST_LOW = 97


@dataclass
class SeparationEdit:
    channels: list[ChannelInfo]
    changed: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    added: set[str] = field(default_factory=set)
    message: str = ""

    @property
    def is_noop(self) -> bool:
        return not (self.changed or self.removed or self.added)


def diff_edit(before: list[ChannelInfo], after: list[ChannelInfo], message: str = "") -> SeparationEdit:
    """Edit a partir de duas listas: instância nova com o mesmo id conta como alterada."""
    old = {ch.id: ch for ch in before}
    new_ids = {ch.id for ch in after}
    return SeparationEdit(
        list(after),
        changed={ch.id for ch in after if ch.id in old and ch is not old[ch.id]},
        removed={cid for cid in old if cid not in new_ids},
        added={ch.id for ch in after if ch.id not in old},
        message=message,
    )


# ------------------------------------------------------------------ helpers

def coverage(channel: ChannelInfo) -> float:
    return 0.0 if channel.mask is None else float(np.asarray(channel.mask, dtype=np.float32).mean())


def _label(channel: ChannelInfo) -> str:
    return f"{separation_display_name(channel.name)} {channel.key or ''}".lower()


def _has_word(channel: ChannelInfo, words: tuple[str, ...]) -> bool:
    label = _label(channel)
    return any(w in label for w in words)


def is_underbase(channel: ChannelInfo) -> bool:
    return channel.role == "underbase" or "underbase" in _label(channel)


def is_top_white(channel: ChannelInfo) -> bool:
    if is_underbase(channel):
        return False
    return channel.role == "highlight" or _has_word(channel, ("white", "branco"))


def is_white(channel: ChannelInfo) -> bool:
    return is_underbase(channel) or is_top_white(channel)


def is_black(channel: ChannelInfo) -> bool:
    return channel.role == "key" or _has_word(channel, ("black", "preto"))


def source_mask(channel: ChannelInfo) -> np.ndarray:
    base = channel.raw_mask if channel.raw_mask is not None else channel.mask
    return np.clip(np.asarray(base, dtype=np.float32), 0.0, 1.0)


def _with_raw(channel: ChannelInfo, raw: np.ndarray) -> ChannelInfo:
    """Cópia da separação com nova máscara bruta (os ajustes da separação continuam valendo)."""
    out = clone_channel(channel)
    out.set_mask(np.clip(raw, 0.0, 1.0).astype(np.float32))
    return out


def screen(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Soma de tinta limitada a 100%: 1 - (1-a)(1-b)."""
    a = np.clip(np.asarray(a, dtype=np.float32), 0.0, 1.0)
    b = np.clip(np.asarray(b, dtype=np.float32), 0.0, 1.0)
    return (1.0 - (1.0 - a) * (1.0 - b)).astype(np.float32)


def _rgb_to_lab(rgb) -> np.ndarray:
    arr = np.asarray(rgb, dtype=np.float32).reshape(-1, 1, 3) / 255.0
    return cv2.cvtColor(arr, cv2.COLOR_RGB2Lab).reshape(-1, 3)


def color_distance(rgb_a, rgb_b) -> float:
    a, b = _rgb_to_lab([rgb_a, rgb_b])
    return float(np.linalg.norm(a - b))


@dataclass(frozen=True)
class ImageLab:
    """Lab normalizado da arte: L 0..1, croma (unidades Lab) e matiz em graus."""

    lightness: np.ndarray
    chroma: np.ndarray
    hue: np.ndarray
    alpha: np.ndarray

    @classmethod
    def from_rgb(cls, rgb_u8: np.ndarray, alpha: np.ndarray | None = None) -> ImageLab:
        rgb = np.asarray(rgb_u8)
        f = (rgb[..., :3].astype(np.float32) / 255.0) if rgb.dtype == np.uint8 else np.clip(rgb[..., :3], 0, 1).astype(np.float32)
        lab = cv2.cvtColor(np.ascontiguousarray(f), cv2.COLOR_RGB2Lab)
        a, b = lab[..., 1], lab[..., 2]
        h, w = f.shape[:2]
        al = np.ones((h, w), np.float32) if alpha is None else np.clip(np.asarray(alpha, np.float32), 0, 1)
        return cls(
            lightness=(lab[..., 0] / 100.0).astype(np.float32),
            chroma=np.hypot(a, b).astype(np.float32),
            hue=(np.degrees(np.arctan2(b, a)) % 360.0).astype(np.float32),
            alpha=al,
        )

    def hue_weight(self, center: float, width: float) -> np.ndarray:
        d = np.abs((self.hue - center + 180.0) % 360.0 - 180.0)
        return np.clip(1.0 - d / width, 0.0, 1.0).astype(np.float32)

    def chroma_ramp(self, full_at: float) -> np.ndarray:
        return np.clip(self.chroma / full_at, 0.0, 1.0).astype(np.float32)


def _smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return (x * x * (3.0 - 2.0 * x)).astype(np.float32)


def _shape_ok(channel: ChannelInfo, shape: tuple[int, int]) -> bool:
    return channel.mask is not None and tuple(channel.mask.shape[:2]) == tuple(shape)


def _insert_before_whites(channels: list[ChannelInfo], new: ChannelInfo) -> list[ChannelInfo]:
    out = list(channels)
    idx = next((i for i, ch in enumerate(out) if is_top_white(ch)), len(out))
    out.insert(idx, new)
    return out


# ------------------------------------------------------------------ Merge Gray / Purple / Turquoise

_FAMILY_WORDS: dict[str, tuple[str, ...]] = {
    "gray": ("gray", "grey", "cinza"),
    "purple": ("purple", "violet", "roxo", "lilac", "lavender"),
    "turquoise": ("turquoise", "turquesa", "teal", "aqua"),
}
_RED_WORDS = ("red", "vermelh")
_BLUE_WORDS = ("blue", "azul")


def family_channels(channels: list[ChannelInfo], family: MergeFamily) -> list[ChannelInfo]:
    words = _FAMILY_WORDS[family]
    found = [ch for ch in channels if not is_white(ch) and not is_black(ch) and _has_word(ch, words)]
    if not found and family == "gray":
        found = [ch for ch in channels if ch.role == "neutral" and not is_white(ch) and not is_black(ch)]
    return [ch for ch in found if ch.mask is not None]


def _nearest(candidates: list[ChannelInfo], rgb) -> ChannelInfo | None:
    usable = [ch for ch in candidates if ch.mask is not None]
    if not usable:
        return None
    return min(usable, key=lambda ch: color_distance(ch.color_rgb, rgb))


def _named_or_nearest(channels: list[ChannelInfo], words: tuple[str, ...], rgb, exclude: set[str]) -> ChannelInfo | None:
    pool = [ch for ch in channels if ch.id not in exclude and not is_white(ch) and not is_black(ch) and ch.mask is not None]
    named = [ch for ch in pool if _has_word(ch, words)]
    if named:
        return named[0]
    return _nearest(pool, rgb)


def merge_targets(channels: list[ChannelInfo], family: MergeFamily, sources: list[ChannelInfo]) -> list[ChannelInfo]:
    """SS4: Gray → White final; Purple → Red + Blue; Turquoise → Blue."""
    exclude = {ch.id for ch in sources}
    if family == "gray":
        whites = [ch for ch in channels if is_top_white(ch) and ch.mask is not None]
        if whites:
            return [whites[-1]]
        mean_rgb = np.mean([ch.color_rgb for ch in sources], axis=0)
        pool = [ch for ch in channels if ch.id not in exclude and not is_underbase(ch) and ch.mask is not None]
        target = _nearest(pool, mean_rgb)
        return [target] if target is not None else []
    if family == "purple":
        targets = [
            _named_or_nearest(channels, _RED_WORDS, (255, 0, 0), exclude),
            _named_or_nearest(channels, _BLUE_WORDS, (0, 0, 255), exclude),
        ]
    else:
        targets = [_named_or_nearest(channels, _BLUE_WORDS, (0, 0, 255), exclude)]
    unique: list[ChannelInfo] = []
    for t in targets:
        if t is not None and all(t.id != u.id for u in unique):
            unique.append(t)
    return unique


def merge_family(channels: list[ChannelInfo], family: MergeFamily) -> SeparationEdit | None:
    """Funde as separações da família nas separações-alvo; a família sai da lista."""
    sources = family_channels(channels, family)
    if not sources:
        return None
    targets = merge_targets(channels, family, sources)
    if not targets:
        return None
    new_by_id: dict[str, ChannelInfo] = {}
    for target in targets:
        raw = source_mask(target)
        for src in sources:
            if src.mask is not None and src.mask.shape == raw.shape:
                raw = screen(raw, src.mask)
        new_by_id[target.id] = _with_raw(target, raw)
    removed = {ch.id for ch in sources}
    out = [new_by_id.get(ch.id, ch) for ch in channels if ch.id not in removed]
    src_names = ", ".join(separation_display_name(s.name) for s in sources)
    tgt_names = " + ".join(separation_display_name(t.name) for t in targets)
    return SeparationEdit(
        out,
        changed=set(new_by_id),
        removed=removed,
        message=f"Mesclado: {src_names} → {tgt_names}.",
    )


# ------------------------------------------------------------------ Generate Brown / Enhance Red Orange

BROWN_NAME = "Marrom 470"
BROWN_RGB = (110, 62, 36)


def brown_mask(lab: ImageLab, red: np.ndarray | None = None) -> np.ndarray:
    """Marrons: matizes vermelho→laranja com luminância baixa/média (+ Red nas áreas escuras)."""
    warm = lab.hue_weight(55.0, 45.0) * lab.chroma_ramp(30.0)
    dark = _smoothstep((0.68 - lab.lightness) / 0.45) * _smoothstep(lab.lightness / 0.08)
    mask = warm * dark
    if red is not None and red.shape == mask.shape:
        mask = np.maximum(mask, red * 0.85 * dark)
    return np.clip(mask * lab.alpha, 0.0, 1.0).astype(np.float32)


def find_red(channels: list[ChannelInfo]) -> ChannelInfo | None:
    return _named_or_nearest(channels, _RED_WORDS, (255, 0, 0), set())


def generate_brown(channels: list[ChannelInfo], lab: ImageLab) -> SeparationEdit:
    shape = lab.lightness.shape
    red = find_red(channels)
    red_mask = source_mask(red) if red is not None and _shape_ok(red, shape) else None
    mask = brown_mask(lab, red_mask)
    existing = next((ch for ch in channels if _has_word(ch, ("brown", "marrom"))), None)
    if existing is not None and _shape_ok(existing, shape):
        new = _with_raw(existing, mask)
        out = [new if ch.id == existing.id else ch for ch in channels]
        return SeparationEdit(out, changed={existing.id}, message="Separação Marrom regenerada.")
    new = ChannelInfo.create(BROWN_NAME, BROWN_RGB, mask=mask, key="brown", export_name="BROWN 470", role="chromatic")
    if red is not None:
        out = list(channels)
        out.insert(out.index(red) + 1, new)
    else:
        out = _insert_before_whites(channels, new)
    return SeparationEdit(
        out, added={new.id}, message=f"Separação Marrom criada (cobertura {coverage(new):.1%})."
    )


def red_orange_extension(lab: ImageLab) -> np.ndarray:
    """Faixa vermelho→laranja estendida (inclui misturas de baixo croma)."""
    ext = lab.hue_weight(45.0, 40.0) * np.power(lab.chroma_ramp(40.0), 0.8)
    light = _smoothstep(lab.lightness / 0.12) * _smoothstep((1.0 - lab.lightness) / 0.08)
    return np.clip(ext * light * lab.alpha, 0.0, 1.0).astype(np.float32)


def enhance_red_orange(channels: list[ChannelInfo], lab: ImageLab) -> SeparationEdit | None:
    red = find_red(channels)
    if red is None or not _shape_ok(red, lab.lightness.shape):
        return None
    raw = source_mask(red)
    boosted = np.maximum(raw, red_orange_extension(lab))
    new = _with_raw(red, boosted)
    out = [new if ch.id == red.id else ch for ch in channels]
    return SeparationEdit(out, changed={red.id},
                          message=f"{separation_display_name(red.name)}: {coverage(red):.2%} → {coverage(new):.2%}.")


# ------------------------------------------------------------------ Adjust by Saturation Range / Auto Adjust

def saturation_range(mask: np.ndarray, high: int, low: int) -> np.ndarray:
    """SS4 'Adjust by Saturation Range'.

    High Saturation (0..100, padrão 0): satura — o valor (100-high)% passa a imprimir 100%.
    Low Saturation (0..100, padrão 100): remove os dados abaixo de (100-low)%.
    """
    m = np.clip(np.asarray(mask, dtype=np.float32), 0.0, 1.0)
    high = int(np.clip(high, 0, 100))
    low = int(np.clip(low, 0, 100))
    white_point = max(0.01, 1.0 - high / 100.0)
    floor = (100 - low) / 100.0
    out = np.clip(m / white_point, 0.0, 1.0) if high else m.copy()
    if floor > 0:
        out = np.where(m < floor, 0.0, out)
    return out.astype(np.float32)


def adjust_saturation_range(
    channels: list[ChannelInfo], target_ids: list[str] | set[str], high: int, low: int
) -> SeparationEdit:
    targets = set(target_ids)
    changed: set[str] = set()
    out: list[ChannelInfo] = []
    for ch in channels:
        if ch.id in targets and ch.mask is not None and (high or low < 100):
            out.append(_with_raw(ch, saturation_range(source_mask(ch), high, low)))
            changed.add(ch.id)
        else:
            out.append(ch)
    return SeparationEdit(
        out,
        changed=changed,
        message=(
            f"Faixa de saturação aplicada em {len(changed)} separação(ões) "
            f"(encharcar {high}, aliviar {low})."
        ),
    )


def auto_adjust(channels: list[ChannelInfo], target_ids: list[str] | set[str] | None = None) -> SeparationEdit:
    """Faixa predeterminada sobre as separações de cor (brancos ficam como estão)."""
    pool = set(target_ids) if target_ids is not None else {ch.id for ch in channels}
    ids = {ch.id for ch in channels if ch.id in pool and not is_white(ch)}
    edit = adjust_saturation_range(channels, ids, AUTO_ADJUST_HIGH, AUTO_ADJUST_LOW)
    edit.message = (
        f"Ajuste automático: {len(edit.changed)} separação(ões) "
        f"(encharcar {AUTO_ADJUST_HIGH}, aliviar {AUTO_ADJUST_LOW})."
    )
    return edit


# ------------------------------------------------------------------ Press Fit

def _downsample(mask: np.ndarray, limit: int = 256) -> np.ndarray:
    h, w = mask.shape[:2]
    scale = min(1.0, limit / max(h, w))
    if scale >= 1.0:
        return np.asarray(mask, dtype=np.float32)
    return cv2.resize(np.asarray(mask, dtype=np.float32), (max(1, int(w * scale)), max(1, int(h * scale))),
                      interpolation=cv2.INTER_AREA)


_CHROMATIC_MIN = 15.0


def _closest_color(source_rgb, candidates: dict[str, tuple]) -> str:
    """Cromática → cromática de matiz mais próximo; neutra → menor distância Lab."""
    lab = dict(zip([None, *candidates], _rgb_to_lab([source_rgb, *candidates.values()])))
    src = lab.pop(None)

    def chroma(v) -> float:
        return float(np.hypot(v[1], v[2]))

    def hue(v) -> float:
        return float(np.degrees(np.arctan2(v[2], v[1])) % 360.0)

    if chroma(src) >= _CHROMATIC_MIN:
        chromatic = [cid for cid, v in lab.items() if chroma(v) >= _CHROMATIC_MIN]
        if chromatic:
            return min(chromatic, key=lambda cid: abs((hue(lab[cid]) - hue(src) + 180.0) % 360.0 - 180.0))
    return min(lab, key=lambda cid: float(np.linalg.norm(lab[cid] - src)))


def press_fit_plan(channels: list[ChannelInfo], screens: int) -> list[tuple[str, str]]:
    """Pares (origem → alvo): a separação de menor cobertura vai para a cor mais próxima.

    A Underbase fica travada na tela #1 e não entra em fusões.
    """
    screens = max(1, int(screens))
    masks = {ch.id: _downsample(ch.mask) for ch in channels if ch.mask is not None}
    rgb = {ch.id: tuple(ch.color_rgb) for ch in channels}
    locked = {ch.id for ch in channels if is_underbase(ch)}
    alive = [ch.id for ch in channels]
    plan: list[tuple[str, str]] = []
    while len(alive) > screens:
        movable = [cid for cid in alive if cid not in locked and cid in masks]
        if len(movable) < 2:
            break
        source = min(movable, key=lambda cid: (float(masks[cid].mean()), -alive.index(cid)))
        target = _closest_color(rgb[source], {cid: rgb[cid] for cid in movable if cid != source})
        masks[target] = screen(masks[target], masks[source])
        alive.remove(source)
        plan.append((source, target))
    return plan


def press_fit(channels: list[ChannelInfo], screens: int) -> SeparationEdit:
    plan = press_fit_plan(channels, screens)
    by_id = {ch.id: ch for ch in channels}
    raws = {ch.id: source_mask(ch) for ch in channels if ch.mask is not None}
    removed: set[str] = set()
    changed: set[str] = set()
    for source, target in plan:
        src_mask = raws[source] if source in changed else by_id[source].mask
        raws[target] = screen(raws[target], src_mask)
        removed.add(source)
        changed.add(target)
        changed.discard(source)
    changed -= removed
    out = [_with_raw(ch, raws[ch.id]) if ch.id in changed else ch for ch in channels if ch.id not in removed]
    names = ", ".join(
        f"{separation_display_name(by_id[s].name)} → {separation_display_name(by_id[t].name)}" for s, t in plan
    )
    return SeparationEdit(
        out,
        changed=changed,
        removed=removed,
        message=(
            f"Encaixe na mesa: {len(channels)} → {len(out)} tela(s)"
            + (f" ({names})" if names else ".")
        ),
    )


def press_fit_assignment(channels: list[ChannelInfo], screens: int) -> dict[str, int]:
    """Tela (1..N) de cada separação a partir do plano automático; a Underbase fica na tela 1.

    As separações que sobram ocupam as telas seguintes na ordem de impressão; as fundidas vão
    para a tela do alvo.
    """
    screens = max(1, int(screens))
    plan = press_fit_plan(channels, screens)
    target_of = dict(plan)
    assignment: dict[str, int] = {}
    next_screen = 1
    has_underbase = any(is_underbase(ch) for ch in channels)
    if has_underbase:
        next_screen = 2
    for ch in channels:
        if is_underbase(ch):
            assignment[ch.id] = 1
        elif ch.id not in target_of:
            assignment[ch.id] = (next_screen - 1) % screens + 1
            next_screen += 1
    for ch in channels:
        cid = ch.id
        while cid in target_of:
            cid = target_of[cid]
        assignment.setdefault(ch.id, assignment.get(cid, 1))
    return assignment


def rotate_assignment(channels: list[ChannelInfo], assignment: dict[str, int], screens: int,
                      clockwise: bool = True) -> dict[str, int]:
    """Girar o carrossel: tela s → s % N + 1 (anti-horário: o inverso); a Underbase não sai da 1."""
    n = max(1, int(screens))
    locked = {ch.id for ch in channels if is_underbase(ch)}
    step = 0 if clockwise else -2
    return {cid: s if cid in locked else (s + step) % n + 1 for cid, s in assignment.items()}


def press_fit_by_screens(
    channels: list[ChannelInfo], assignment: dict[str, int], prefer: set[str] | None = None
) -> SeparationEdit:
    """Funde as separações que estão na mesma tela; o resultado segue a ordem das telas.

    Fica a separação preferida (``prefer``, ex.: as que sobram no plano automático) ou a de maior
    cobertura; a Underbase nunca é fundida e vem antes das outras da tela 1.
    """
    prefer = prefer or set()
    groups: dict[int, list[ChannelInfo]] = {}
    for ch in channels:
        groups.setdefault(int(assignment.get(ch.id, 1)), []).append(ch)
    out: list[ChannelInfo] = []
    changed: set[str] = set()
    removed: set[str] = set()
    merges: list[str] = []
    for screen_no in sorted(groups):
        members = groups[screen_no]
        out.extend(ch for ch in members if is_underbase(ch))
        inks = [ch for ch in members if not is_underbase(ch)]
        with_mask = [ch for ch in inks if ch.mask is not None]
        if len(with_mask) < 2:
            out.extend(inks)
            continue
        keep = max(with_mask, key=lambda ch: (ch.id in prefer, coverage(ch)))
        raw = source_mask(keep)
        for ch in with_mask:
            if ch is not keep and ch.mask.shape == raw.shape:
                raw = screen(raw, ch.mask)
                removed.add(ch.id)
        merged = any(ch.id in removed for ch in with_mask)
        out.append(_with_raw(keep, raw) if merged else keep)
        out.extend(ch for ch in inks if ch.mask is None)
        if merged:
            changed.add(keep.id)
            gone = [separation_display_name(ch.name) for ch in with_mask if ch.id in removed]
            merges.append(f"{', '.join(gone)} → {separation_display_name(keep.name)}")
    if [ch.id for ch in out] != [ch.id for ch in channels if ch.id not in removed]:
        # só a ordem de impressão mudou: o undo guarda a ordem antes/depois
        changed |= {ch.id for ch in out}
    used = len({int(assignment.get(ch.id, 1)) for ch in channels})
    detail = f" ({'; '.join(merges)})" if merges else ""
    return SeparationEdit(
        out,
        changed=changed,
        removed=removed,
        message=(
            f"Encaixe na mesa: {len(channels)} separações → {len(out)} em {used} tela(s){detail}."
        ),
    )


# ------------------------------------------------------------------ Generate Black

@dataclass(frozen=True)
class BlackSettings:
    shadow_range: float  # 0..1: luminância até onde o preto alcança
    max_density: float = 1.0
    gamma: float = 1.0
    detail: float = 0.0  # reforço de contraste local
    sharpen: float = 0.0  # máscara de nitidez (unsharp)


BLACK_PRESETS: dict[str, BlackSettings] = {
    "skeletal": BlackSettings(shadow_range=0.22, gamma=1.6),
    "detailed": BlackSettings(shadow_range=0.45, gamma=0.9, detail=0.8),
    "sharper": BlackSettings(shadow_range=0.45, gamma=0.9, detail=0.8, sharpen=1.4),
}


def black_mask(lab: ImageLab, settings: BlackSettings) -> np.ndarray:
    t = float(np.clip(settings.shadow_range, 0.01, 1.0))
    tonal = _smoothstep((t - lab.lightness) / t)
    if settings.detail > 0:
        blur = cv2.GaussianBlur(lab.lightness, (0, 0), 3.0)
        local = np.clip((blur - lab.lightness) * 4.0, 0.0, 1.0)
        reach = _smoothstep((t * 1.6 - lab.lightness) / (t * 1.6))
        tonal = np.maximum(tonal, local * reach * settings.detail)
    protection = np.clip(1.0 - lab.chroma / 40.0, 0.0, 1.0)
    key = np.power(np.clip(tonal * protection, 0.0, 1.0), settings.gamma)
    if settings.sharpen > 0:
        soft = cv2.GaussianBlur(key, (0, 0), 1.5)
        key = key + settings.sharpen * (key - soft)
    key = np.clip(key, 0.0, float(np.clip(settings.max_density, 0.0, 1.0)))
    return np.minimum(key, lab.alpha).astype(np.float32)


def _insert_after_underbase(channels: list[ChannelInfo], new: ChannelInfo) -> list[ChannelInfo]:
    """SS4: a Black é impressa logo depois da Underbase (no começo quando não há Underbase)."""
    out = list(channels)
    idx = next((i + 1 for i, ch in enumerate(out) if is_underbase(ch)), 0)
    out.insert(idx, new)
    return out


def generate_black(
    channels: list[ChannelInfo], lab: ImageLab, variant: BlackVariant, settings: BlackSettings | None = None
) -> SeparationEdit:
    """Black a partir da arte (``lab``); repetir substitui a Black existente."""
    cfg = settings or BLACK_PRESETS[variant]
    mask = black_mask(lab, cfg)
    titles = {"skeletal": "Esquelético", "detailed": "Detalhado", "sharper": "Mais nítido"}
    title = titles.get(variant, variant)
    existing = next((ch for ch in channels if is_black(ch) and _shape_ok(ch, mask.shape)), None)
    if existing is not None:
        new = _with_raw(existing, mask)
        out = _insert_after_underbase([ch for ch in channels if ch.id != existing.id], new)
        return SeparationEdit(
            out,
            changed={existing.id},
            message=f"Preto ({title}) regenerado: cobertura {coverage(new):.1%}.",
        )
    new = ChannelInfo.create("Preto", (0, 0, 0), mask=mask, channel_id=str(uuid.uuid4()),
                             key="black", export_name="BLACK", role="key")
    out = _insert_after_underbase(channels, new)
    return SeparationEdit(
        out, added={new.id}, message=f"Preto ({title}) criado: cobertura {coverage(new):.1%}."
    )
