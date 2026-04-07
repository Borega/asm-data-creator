from qfluentwidgets import FluentWindow, NavigationItemPosition, FluentIcon as FIF

from gui.app_controller import AppController
from gui.pages.input_page import InputPage
from gui.pages.diff_review_page import DiffReviewPage
from gui.pages.settings_page import SettingsPage


class MainWindow(FluentWindow):
    """Main application window with Fluent Design sidebar navigation."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(1024, 768)
        self.setWindowTitle("ASM Generator")

        # Controller must be created before pages so it can be passed to them
        self._controller = AppController(self)

        # Create pages — each receives the controller reference
        self._input_page = InputPage(controller=self._controller)
        self._diff_page = DiffReviewPage(controller=self._controller)
        self._settings_page = SettingsPage(controller=self._controller)

        # Wire pages into controller (connects signals, restores paths)
        self._controller.set_pages(self._input_page, self._diff_page, self._settings_page)

        # Register navigation
        self.addSubInterface(
            self._input_page,
            FIF.FOLDER,
            "Input",
            position=NavigationItemPosition.SCROLL,
        )
        self.addSubInterface(
            self._diff_page,
            FIF.SYNC,
            "Diff Review",
            position=NavigationItemPosition.SCROLL,
        )
        self.addSubInterface(
            self._settings_page,
            FIF.SETTING,
            "Settings",
            position=NavigationItemPosition.BOTTOM,
        )

    def switchTo(self, page) -> None:
        """Navigate to a sub-interface page (called by AppController)."""
        self.stackedWidget.setCurrentWidget(page)
        self.navigationInterface.setCurrentItem(page.objectName())
