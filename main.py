import os
import sys


def _frozen_qt_fix() -> None:
    """Set QT_QPA_PLATFORM_PLUGIN_PATH for PyInstaller --onedir builds.

    Must be called BEFORE QApplication is constructed. Qt reads the platform
    plugin path from the environment during QApplication.__init__; setting it
    afterwards has no effect.

    Path layout: collect_all('PyQt6') places platform DLLs at:
    _MEIPASS/PyQt6/Qt6/plugins/platforms/qwindows.dll
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        plugin_path = os.path.join(
            sys._MEIPASS, "PyQt6", "Qt6", "plugins", "platforms"
        )
        os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", plugin_path)


if __name__ == "__main__":
    _frozen_qt_fix()                          # 1. Fix Qt paths BEFORE QApplication

    from PyQt6.QtWidgets import QApplication
    from qfluentwidgets import setTheme, Theme

    app = QApplication(sys.argv)              # 2. QApplication BEFORE any widget
    setTheme(Theme.AUTO)                      # 3. setTheme AFTER QApplication, BEFORE window

    from gui.main_window import MainWindow    # 4. Import after QApplication (safe)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())                      # 5. app.exec() — no trailing underscore (PyQt6)
