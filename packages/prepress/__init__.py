"""API pública da camada modular de pré-impressão."""

from packages.prepress.models import (
    FilmConfig,
    JointCleanupConfig,
    OverprintConfig,
    PrepressConfig,
    ScreenConfig,
    ToneCurveConfig,
    TrapConfig,
    WhiteConfig,
)
from packages.prepress.operations import JointCleanupReport, PrepressPlate, joint_cleanup_masks
from packages.prepress.digital_proof import (
    DIGITAL_PROOF_LABEL,
    DigitalProof,
    DigitalProofCancelled,
    render_digital_proof,
)
from packages.prepress.pdf_export import (
    export_films_pdf,
    manifest_path_for,
    render_film_page,
    write_manifest_atomic,
)
from packages.prepress.pipeline import (
    PrepressResult,
    prepare_plates,
    prepare_plates_with_diagnostics,
)

__all__ = [
    "FilmConfig",
    "DIGITAL_PROOF_LABEL",
    "DigitalProof",
    "DigitalProofCancelled",
    "JointCleanupConfig",
    "JointCleanupReport",
    "OverprintConfig",
    "PrepressConfig",
    "PrepressPlate",
    "PrepressResult",
    "ScreenConfig",
    "ToneCurveConfig",
    "TrapConfig",
    "WhiteConfig",
    "export_films_pdf",
    "manifest_path_for",
    "joint_cleanup_masks",
    "prepare_plates",
    "prepare_plates_with_diagnostics",
    "render_film_page",
    "render_digital_proof",
    "write_manifest_atomic",
]
