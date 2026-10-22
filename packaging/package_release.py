from pathlib import Path
import hashlib
import zipfile

root = Path(__file__).resolve().parents[1]
output = root / "release"
output.mkdir(exist_ok=True)
checksums = []
for edition, filename in [
    ("ADNY Separador", "ADNY-Separador-Completa-Windows-x64.zip"),
    ("ADNY Separador Clean", "ADNY-Separador-Clean-Windows-x64.zip"),
]:
    source = root / "dist" / edition
    assert (source / (edition + ".exe")).is_file()
    assert (source / "_internal" / "scf8" / "assets" / "adny_separador.ico").is_file()
    target = output / filename
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source.parent))
        archive.write(root / "README.md", edition + "/LEIA-ME.md")
    checksums.append(hashlib.sha256(target.read_bytes()).hexdigest() + "  " + filename)
(output / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
