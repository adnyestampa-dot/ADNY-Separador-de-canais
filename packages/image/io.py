from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from packages.core.models.image_document import ImageDocument

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".psd"}
OPEN_FILE_FILTER = (
    "Imagens (*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp *.psd);;"
    "Photoshop PSD (*.psd);;"
    "Todos os arquivos (*.*)"
)


def _open_pil(path: Path) -> Image.Image:
    """Abre raster; PSD usa o composite (arte pronta para o motor)."""
    if path.suffix.lower() == ".psd":
        from psd_tools import PSDImage

        psd = PSDImage.open(path)
        composite = psd.composite()
        if composite is None:
            raise ValueError("PSD sem imagem composite legível")
        # Mantém o PSD aberto só o necessário; composite já é PIL independente.
        return composite.copy() if hasattr(composite, "copy") else composite
    with Image.open(path) as img:
        return img.copy()


def load_image(path: str | Path) -> ImageDocument:
    """Load image from disk and return normalized RGB ImageDocument."""
    path = Path(path)
    suffix = path.suffix.lower()
    if not suffix:
        raise ValueError(
            f"Formato não suportado: arquivo sem extensão ({path.name!r}). "
            "Use PNG, JPG, BMP, TIFF, WEBP ou PSD."
        )
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Formato não suportado: {suffix or '(sem extensão)'}. "
            "Use PNG, JPG, BMP, TIFF, WEBP ou PSD."
        )

    logger.info("Abrindo imagem: %s", path)
    img = _open_pil(path)
    try:
        doc = ImageDocument.from_pil(img, str(path.resolve()))
    finally:
        img.close()
    logger.info("Imagem carregada: %dx%d dpi=%s", doc.width, doc.height, doc.dpi)
    return doc


def save_image(
    image: Image.Image,
    path: str | Path,
    dpi: tuple[float, float] = (300.0, 300.0),
) -> None:
    """Save PIL image to disk with optional DPI metadata."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = "PNG" if path.suffix.lower() == ".png" else None
    image.save(path, format=fmt, dpi=dpi)
    logger.info("Imagem exportada: %s (%dx%d @ %s DPI)", path, image.width, image.height, dpi[0])
