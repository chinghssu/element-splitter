# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for element-splitter.
#
#   pyinstaller main.spec
#
# Bundles the MobileSAM checkpoint (models/mobile_sam.pt, ~40MB) so the packaged app
# works offline for the cut-out feature. LaMa's checkpoint (~196MB) is NOT bundled —
# inpaint_engine.py downloads it on first use via torch.hub, same as the unpackaged
# app; bundling it would add ~200MB to every build for a feature not every user needs.
#
# mobile_sam, timm and simple_lama_inpainting all do some import-time registry/plugin
# work that PyInstaller's static analysis can miss, so their packages are pulled in
# wholesale via collect_all() rather than relying on hidden-import guesses.
from PyInstaller.utils.hooks import collect_all

datas = [
    ("models/mobile_sam.pt", "models"),
    ("models/SOURCES.json", "models"),
]
binaries = []
hiddenimports = []

for pkg in ("mobile_sam", "timm", "simple_lama_inpainting", "torch", "torchvision", "cv2"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # PyInstaller refuses to bundle two Qt bindings side by side. torch's own build
    # hook pulls in optional dev/notebook dependencies (matplotlib, IPython, sphinx,
    # pytest, ...) that this app never imports; matplotlib in turn probes for a Qt
    # backend and drags in PyQt5/PyQt6, which conflicts with our PySide6 GUI. None of
    # this is needed at runtime, so exclude it — this also meaningfully shrinks the
    # bundle.
    excludes=[
        "PyQt5",
        "PyQt6",
        "PySide2",
        "matplotlib",
        "IPython",
        "sphinx",
        "pytest",
        "notebook",
        "jedi",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="element-splitter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI app — no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="element-splitter",
)

app = BUNDLE(
    coll,
    name="element-splitter.app",
    icon=None,
    bundle_identifier="com.chinghssu.element-splitter",
)
