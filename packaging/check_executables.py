from pathlib import Path
import subprocess
import tempfile
from PIL import Image, ImageDraw
from psd_tools import PSDImage
from psd_tools.constants import Resource

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as temporary:
    scratch = Path(temporary)
    image = Image.new("RGBA", (128, 128), (0, 0, 0, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 60, 115), fill=(240, 45, 25, 255))
    draw.ellipse((42, 15, 118, 90), fill=(35, 130, 235, 255))
    draw.rectangle((65, 92, 115, 115), fill=(240, 190, 10, 255))
    image.save(scratch / "entrada.png", dpi=(300, 300))
    for edition in ["ADNY Separador", "ADNY Separador Clean"]:
        exe = root / "dist" / edition / (edition + ".exe")
        output = scratch / (edition + ".psd")
        result = subprocess.run([str(exe), "--selftest", str(scratch / "entrada.png"), str(output)], timeout=180)
        if result.returncode:
            report = output.with_suffix(".selftest.txt")
            raise RuntimeError(report.read_text(encoding="utf-8") if report.exists() else "Falha no executavel: " + edition)
        psd = PSDImage.open(output)
        assert psd.size == (128, 128)
        names = psd.image_resources.get_data(Resource.ALPHA_NAMES_PASCAL)
        assert names and psd.channels > 3
        print(edition + ": exportacao PSD validada")
