# ASM Generator

A Windows desktop application for generating Apple School Manager (ASM) CSV export files from school administration exports.

## Building the Windows Executable

### Prerequisites

```
pip install -r requirements.txt
```

### Build command

```
pyinstaller asm_generator.spec
```

Output: `dist/ASM-Generator/ASM-Generator.exe` (the whole `dist/ASM-Generator/`
folder must be distributed together — the `.exe` is not standalone).

### Run in development (no build required)

```
python main.py
```

### Verify the frozen build

1. Run `dist\ASM-Generator\ASM-Generator.exe`
2. Expected: FluentWindow opens with "Input", "Diff Review", "Settings" sidebar items
3. Click through all three sidebar items — each shows a placeholder page
4. Close the window — exit code 0 (no crash)

### Debugging Qt platform plugin errors

If you see:
```
This application failed to start because no Qt platform plugin could be initialized.
```

Enable Qt plugin debug output and re-run:
```
set QT_DEBUG_PLUGINS=1
dist\ASM-Generator\ASM-Generator.exe
```

This prints the exact paths Qt searched. The `_frozen_qt_fix()` function in `main.py`
sets `QT_QPA_PLATFORM_PLUGIN_PATH` to `_MEIPASS/PyQt6/Qt6/plugins/platforms/`. If the
debug output shows Qt looking in a different path, update the path in `_frozen_qt_fix()`.

To inspect what PyInstaller bundled:
```python
# Run from a frozen build (add temporarily to main.py for debugging):
import os, sys
for root, dirs, files in os.walk(sys._MEIPASS):
    for f in files:
        if "platform" in f.lower() or f.endswith(".dll"):
            print(os.path.join(root, f))
```

### Distribution

Zip the entire `dist/ASM-Generator/` folder and send to the admin machine.
No Python installation is required on the target machine.

## Development

### Running tests

```
python -m pytest tests/ -v
```

### Project structure

- `asm_generator/` — core library (CSV parsing, transformation, output)
- `gui/` — PyQt6 + PyQt6-Fluent-Widgets GUI
- `main.py` — application entry point
- `diff_engine.py` — compares current ASM output against last snapshot
- `snapshot_store.py` — persists last-run snapshot to `%LOCALAPPDATA%`
- `asm_generator.spec` — PyInstaller build spec
- `generate_asm.py` — legacy CLI entry point
