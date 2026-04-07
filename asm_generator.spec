# asm_generator.spec
# Build command: pyinstaller asm_generator.spec
# Output:        dist/ASM-Generator/ASM-Generator.exe
#
# Requires: pip install pyinstaller PyQt6 PyQt6-Fluent-Widgets platformdirs
#
# Qt platform plugin fix: main.py sets QT_QPA_PLATFORM_PLUGIN_PATH at startup
# when sys.frozen is True (see _frozen_qt_fix() function in main.py).

from PyInstaller.utils.hooks import collect_all

# Collect ALL files, binaries, and hidden imports for PyQt6 and qfluentwidgets.
# Without collect_all, PyInstaller's static analysis misses dynamically loaded
# Qt modules (platform plugins, image format plugins, etc.), causing runtime errors.
datas, binaries, hiddenimports = [], [], []
for pkg in ("PyQt6", "qfluentwidgets"):
    _d, _b, _h = collect_all(pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas + [
        ("gui/assets/icon.ico", "gui/assets"),  # bundle the window icon
    ],
    hiddenimports=hiddenimports + [
        "asm_generator",
        "asm_generator.config",
        "asm_generator.parsers",
        "asm_generator.transform",
        "asm_generator.generator",
        "asm_generator.writer",
        "diff_engine",
        "snapshot_store",
        "platformdirs",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        # NOTE: do NOT exclude chardet — asm_generator uses it for encoding detection
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,           # onedir: DLLs go in COLLECT, not embedded in EXE
    name="ASM-Generator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                   # --noconsole: no terminal window for end users
    icon="gui/assets/icon.ico",
    uac_admin=False,                 # SECURITY: never request elevation (T-02-03)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ASM-Generator",            # output folder: dist/ASM-Generator/
)
