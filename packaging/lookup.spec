# -*- mode: python ; coding: utf-8 -*-
"""Windows build for Lookup. Qt is imported before MuPDF so their DLLs do not crash the build."""

from pathlib import Path

import PySide6  # noqa: F401
from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parent
pymupdf_datas, pymupdf_binaries, pymupdf_hidden = collect_all("pymupdf")
stem_datas, stem_binaries, stem_hidden = collect_all("snowballstemmer")

block_cipher = None

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=pymupdf_binaries + stem_binaries,
    datas=pymupdf_datas + stem_datas,
    hiddenimports=[
        "pdflookup",
        "pdflookup.window",
        "pdflookup.view",
        "pdflookup.pdfio",
        "pdflookup.search",
        "pdflookup.style",
        "pdflookup.textutil",
        "pdflookup.model",
        "snowballstemmer",
    ]
    + pymupdf_hidden
    + stem_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "packaging" / "rthook_qt_first.py")],
    excludes=["tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Lookup",
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
    icon=str(ROOT / "packaging" / "lookup.ico"),
    version=str(ROOT / "packaging" / "lookup.version.txt"),
    manifest=str(ROOT / "packaging" / "lookup.manifest"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Lookup",
)
