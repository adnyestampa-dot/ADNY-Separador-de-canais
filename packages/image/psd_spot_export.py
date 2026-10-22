from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PIL import Image

from packages.core.models.channel_info import ChannelInfo

logger = logging.getLogger(__name__)

SPOT_SOLIDITY = 100


def export_spot_psd(
    channels: list[ChannelInfo],
    path: str | Path,
    *,
    composite: Image.Image | None = None,
) -> None:
    """Exporta PSD com canais spot (100% solidez), sem camadas RGB."""
    from psd_tools.constants import AlphaChannelMode, ColorMode, ColorSpaceID, Compression, Resource
    from psd_tools.psd import PSD
    from psd_tools.psd.header import FileHeader
    from psd_tools.psd.image_data import ImageData
    from psd_tools.psd.image_resources import (
        AlphaChannel,
        AlphaIdentifiers,
        AlphaNamesPascal,
        AlphaNamesUnicode,
        DisplayInfo,
        ImageResource,
        ImageResources,
    )
    from psd_tools.psd.layer_and_mask import LayerAndMaskInformation

    export_channels = [ch for ch in channels if ch.mask is not None]
    if not export_channels:
        raise ValueError("Nenhum canal com máscara para exportar.")

    first_mask = export_channels[0].mask
    assert first_mask is not None
    h, w = first_mask.shape[:2]

    if composite is not None:
        rgb_img = composite.convert("RGB").resize((w, h), Image.Resampling.BILINEAR)
    else:
        rgb_img = _compose_rgb_preview(export_channels, (h, w))

    rgb_u8 = np.asarray(rgb_img, dtype=np.uint8)

    spot_names: list[str] = []
    spot_rgbs: list[tuple[int, int, int]] = []
    spot_arrays: list[np.ndarray] = []

    for ch in export_channels:
        mask = ch.mask
        assert mask is not None
        if mask.shape[:2] != (h, w):
            mask_img = Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8), mode="L")
            mask_img = mask_img.resize((w, h), Image.Resampling.BILINEAR)
            mask = np.asarray(mask_img, dtype=np.float32) / 255.0

        # Convenção silk screen / Separation Studio: canal spot armazena máscara invertida.
        spot_arr = 1.0 - np.clip(mask.astype(np.float32), 0.0, 1.0)
        spot_names.append(ch.name)
        spot_rgbs.append(ch.color_rgb)
        spot_arrays.append(spot_arr)

    num_channels = 3 + len(spot_arrays)
    header = FileHeader(
        version=1,
        channels=num_channels,
        height=h,
        width=w,
        depth=8,
        color_mode=ColorMode.RGB,
    )
    psd_record = PSD(header=header)

    channel_bytes = [rgb_u8[..., i].tobytes() for i in range(3)]
    for arr in spot_arrays:
        channel_bytes.append((np.clip(arr, 0, 1) * 255).astype(np.uint8).tobytes())

    image_data = ImageData(compression=Compression.RAW)
    image_data.set_data(channel_bytes, header)
    psd_record.image_data = image_data

    # Photoshop exige Unicode com NUL final no contador de chars; sem isso corta a
    # última letra (BASE→BAS, CAMISETA PRETA→CAMISETA PRET).
    unicode_names = [f"{name}\0" for name in spot_names]

    resources = ImageResources()
    resources[Resource.ALPHA_NAMES_PASCAL] = ImageResource(
        key=Resource.ALPHA_NAMES_PASCAL, data=AlphaNamesPascal(spot_names)
    )
    resources[Resource.ALPHA_NAMES_UNICODE] = ImageResource(
        key=Resource.ALPHA_NAMES_UNICODE, data=AlphaNamesUnicode(unicode_names)
    )
    resources[Resource.ALPHA_IDENTIFIERS] = ImageResource(
        key=Resource.ALPHA_IDENTIFIERS,
        data=AlphaIdentifiers(list(range(1, len(spot_names) + 1))),
    )

    alpha_channels = []
    for rgb_ref in spot_rgbs:
        r, g, b = [int(v) * 257 for v in rgb_ref]
        alpha_channels.append(
            AlphaChannel(
                ColorSpaceID.RGB,
                r,
                g,
                b,
                0,
                SPOT_SOLIDITY,
                AlphaChannelMode.SPOT,
            )
        )
    resources[Resource.DISPLAY_INFO] = ImageResource(
        key=Resource.DISPLAY_INFO,
        data=DisplayInfo(alpha_channels=alpha_channels),
    )
    psd_record.image_resources = resources
    psd_record.layer_and_mask_information = LayerAndMaskInformation()

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fp:
        psd_record.write(fp)
    logger.info("PSD spot exportado: %s (%d canais)", path, len(spot_names))


def _compose_rgb_preview(channels: list[ChannelInfo], shape: tuple[int, int]) -> Image.Image:
    """Preview RGB simples quando não há composite."""
    from packages.image.textile import compose_with_ground

    ground = (20, 20, 20)
    return compose_with_ground(channels, shape, ground)
