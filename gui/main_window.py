from PyQt6.QtGui import QIcon
from qfluentwidgets import FluentWindow, NavigationItemPosition, FluentIcon as FIF

from gui.pages.input_page import InputPage
from gui.pages.diff_review_page import DiffReviewPage
from gui.pages.settings_page import SettingsPage


class MainWindow(FluentWindow):
    """Main application window with Fluent Design sidebar navigation."""

    def __init__(self):
        super().__init__()
        self.inputPage = InputPage(parent=self)
        self.diffReviewPage = DiffReviewPage(parent=self)
        self.settingsPage = SettingsPage(parent=self)
        self._init_navigation()
        self._init_window()

    def _init_navigation(self):
        self.addSubInterface(
            self.inputPage,
            FIF.FOLDER,
            "Input",
            NavigationItemPosition.SCROLL,
        )
        self.addSubInterface(
            self.diffReviewPage,
            FIF.SYNC,
            "Diff Review",
            NavigationItemPosition.SCROLL,
        )
        self.addSubInterface(
            self.settingsPage,
            FIF.SETTING,
            "Settings",
            NavigationItemPosition.SCROLL,
        )

    def _init_window(self):
        self.setMinimumSize(1024, 768)
        self.setWindowTitle("ASM Generator")
