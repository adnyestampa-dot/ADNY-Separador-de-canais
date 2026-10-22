from __future__ import annotations

import copy

from packages.core.models.channel_info import ChannelInfo


def merge_channels(
    channels: list[ChannelInfo],
    source_id: str,
    target_id: str,
) -> list[ChannelInfo] | None:
    if source_id == target_id:
        return None
    source = next((c for c in channels if c.id == source_id), None)
    target = next((c for c in channels if c.id == target_id), None)
    if source is None or target is None or source.mask is None or target.mask is None:
        return None

    target.merge_from(source)
    return [ch for ch in channels if ch.id != source_id]


def delete_channel(channels: list[ChannelInfo], channel_id: str) -> list[ChannelInfo] | None:
    if not any(c.id == channel_id for c in channels):
        return None
    return [ch for ch in channels if ch.id != channel_id]


def reorder_channels(channels: list[ChannelInfo], ordered_ids: list[str]) -> list[ChannelInfo] | None:
    if set(ordered_ids) != {c.id for c in channels}:
        return None
    by_id = {c.id: c for c in channels}
    return [by_id[cid] for cid in ordered_ids]


def set_channel_color(channel: ChannelInfo, rgb: tuple[int, int, int]) -> None:
    r, g, b = rgb
    channel.set_color_rgb(
        (
            int(max(0, min(255, r))),
            int(max(0, min(255, g))),
            int(max(0, min(255, b))),
        )
    )


def snapshot_channels(channels: list[ChannelInfo]) -> list[ChannelInfo]:
    """Cópia superficial para undo (máscaras compartilhadas até mutação)."""
    return copy.copy(channels)


def clone_channel(channel: ChannelInfo) -> ChannelInfo:
    """Cópia profunda do canal (máscaras e ajustes) preservando o mesmo id."""
    cloned = ChannelInfo(
        id=channel.id,
        name=channel.name,
        color_rgb=tuple(channel.color_rgb),
        key=channel.key,
        export_name=channel.export_name,
        role=channel.role,
        engine_version=channel.engine_version,
        manifest_version=channel.manifest_version,
        profile_hash=channel.profile_hash,
        visible=channel.visible,
        opacity=float(channel.opacity),
        adjustments=channel.adjustments.copy(),
    )
    if channel.raw_mask is not None:
        cloned._raw_mask = channel.raw_mask.copy()
    if channel.mask is not None:
        cloned._mask = channel.mask.copy()
    if channel.layer_image is not None:
        cloned._layer_image = channel.layer_image.copy()
    elif cloned._mask is not None:
        cloned._rebuild_layer()
    return cloned


def restore_channel_from_clone(live: ChannelInfo, snapshot: ChannelInfo) -> None:
    """Restaura estado de um canal vivo a partir de um clone profundo."""
    live.name = snapshot.name
    live.color_rgb = tuple(snapshot.color_rgb)
    live.key = snapshot.key
    live.export_name = snapshot.export_name
    live.role = snapshot.role
    live.engine_version = snapshot.engine_version
    live.manifest_version = snapshot.manifest_version
    live.profile_hash = snapshot.profile_hash
    live.visible = snapshot.visible
    live.opacity = float(snapshot.opacity)
    live.adjustments = snapshot.adjustments.copy()
    live._raw_mask = None if snapshot.raw_mask is None else snapshot.raw_mask.copy()
    live._mask = None if snapshot.mask is None else snapshot.mask.copy()
    if snapshot.layer_image is not None:
        live._layer_image = snapshot.layer_image.copy()
    elif live._mask is not None:
        live._rebuild_layer()
    else:
        live._layer_image = None
