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
        # Defaults resolved against sys._MEIPASS when Settings leaves a path
        # blank (gui/app_controller.py::_resolve). Without these a fresh
        # install cannot generate at all.
        #
        # Only files tracked in git may appear here: a clean clone is what CI
        # and every other school builds from, and PyInstaller fails on a datas
        # entry it cannot find. teacher_aliases.json is deliberately gitignored
        # (it names real staff), so the tracked empty stub ships instead and
        # _resolve falls back to it. locations.csv is per-school and optional —
        # writer.py::_load_location_name_map already degrades to location ids.
        ("teacher_aliases.empty.json", "."),
        ("subject_map.json", "."),
        # CI writes the release tag into it before building; update_check
        # compares it with the latest GitHub release.
        ("VERSION", "."),
    ],
    hiddenimports=hiddenimports + [
        "asm_generator",
        "asm_generator.config",
        "asm_generator.parsers",
        "asm_generator.transform",
        "asm_generator.generator",
        "asm_generator.writer",
        "activity_log",
        "backup_store",
        "diff_baseline",
        "diff_engine",
        "person_pins",
        "settings_store",
        "sftp_client",
        "sftp_credentials",
        "snapshot_store",
        "update_check",
        "platformdirs",
        "paramiko",
        "keyring",
        "keyring.errors",
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
    upx=False,
    console=False,                   # --noconsole: no terminal window for end users
    icon="gui/assets/icon.ico",
    uac_admin=False,                 # SECURITY: never request elevation (T-02-03)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ASM-Generator",            # output folder: dist/ASM-Generator/
)
