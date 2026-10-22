#!/usr/bin/env python3
"""ADNY Separador — entrada principal."""

from __future__ import annotations

import sys
from pathlib import Path

CLONE_ROOT = Path(__file__).resolve().parent
PLATFORM_ROOT = CLONE_ROOT.parent
for path in (CLONE_ROOT, PLATFORM_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def selftest(image_path: str, out_psd: str) -> int:
    """Separa e exporta PSD sem abrir janela (valida o executável compilado)."""
    import traceback

    report = Path(out_psd).with_suffix(".selftest.txt")
    try:
        from PIL import Image

        from packages.core.services.export_service import ExportService
        from packages.skills.fav8_plus.engine import ENGINE_VERSION
        from packages.skills.separate_channels.skill import SeparateChannelsSkill
        from scf8.core.ss4_separation_preset import spot_process_ss4_params

        class _Ctx:
            metadata = {"pil_image": Image.open(image_path).convert("RGBA")}

        result = SeparateChannelsSkill().execute(_Ctx(), spot_process_ss4_params())
        if not result.ok:
            raise RuntimeError("; ".join(result.messages))
        channels = result.artifacts["channels"]
        ok, messages, warnings = ExportService().export_psd(channels, out_psd, keep_channel_names=True)
        report.write_text(
            f"engine={ENGINE_VERSION}\nok={ok}\nplates={[c.name for c in channels]}\n"
            f"messages={messages + warnings}\n",
            encoding="utf-8",
        )
        return 0 if ok else 1
    except Exception:
        report.write_text(traceback.format_exc(), encoding="utf-8")
        return 1


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--selftest":
        return selftest(sys.argv[2], sys.argv[3])

    from scf8.app.main import main as app_main

    return app_main()


if __name__ == "__main__":
    sys.exit(main())
