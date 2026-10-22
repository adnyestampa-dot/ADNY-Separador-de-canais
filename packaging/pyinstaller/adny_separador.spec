# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — ADNY Separador (ADNY Separador)."""

from __future__ import annotations

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_submodules

SPEC_ROOT = Path(SPECPATH).resolve()
ROOT = next(
    candidate
    for candidate in (SPEC_ROOT, *SPEC_ROOT.parents)
    if (candidate / "pyproject.toml").is_file() and (candidate / "packages").is_dir()
)
CLONE = ROOT / "ADNY Separador"
APP_NAME = "ADNY Separador"

sys.path[:0] = [str(CLONE), str(ROOT)]

block_cipher = None

datas = [
    (str(CLONE / "scf8" / "assets" / "adny_separador.ico"), "scf8/assets"),
    (str(CLONE / "scf8" / "ui" / "ss4_theme.qss"), "scf8/ui"),
    (str(ROOT / "apps" / "desktop_qt" / "themes" / "dark_pro.qss"), "apps/desktop_qt/themes"),
    (
        str(ROOT / "packages" / "skills" / "fav8_plus" / "tune_profile.json"),
        "packages/skills/fav8_plus",
    ),
    (str(CLONE / "docs" / "user_guide.html"), "docs"),
]

hiddenimports: list = [
    "packages.skills.fav8_plus.loader",
    "packages.infra.files.bundle",
    "skimage.filters",
    "skimage.morphology",
    "skimage.measure",
    "skimage.color",
    "scipy.ndimage",
    "scipy.special",
    "scipy.optimize",
    "psd_tools",
]
hiddenimports += collect_submodules("scf8")
hiddenimports += collect_submodules("apps.desktop_qt")
hiddenimports += collect_submodules("packages.core")
hiddenimports += collect_submodules("packages.skills")
hiddenimports += collect_submodules("packages.prepress")
hiddenimports += collect_submodules("packages.image")
hiddenimports += collect_submodules("packages.infra")

a = Analysis(
    [str(CLONE / "run.py")],
    pathex=[str(CLONE), str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=list(dict.fromkeys(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "notebook", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Never bundle DLLs from Codex helper tools found through the host PATH.
# Their ICU/runtime libraries can shadow Windows libraries required by Qt.
a.binaries = [
    entry for entry in a.binaries
    if "codex-primary-runtime" not in entry[1].lower()
]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(SPEC_ROOT / "adny_separador.ico"),
    version=str(SPEC_ROOT / "adny_version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
