from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt


class SettingsPage(QWidget):
    """Stub settings page — form fields implemented in Phase 3."""

    def __init__(self, controller=None, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("settings-page")   # REQUIRED
        self._controller = controller
        lbl = QLabel("Settings — Coming soon", self)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.addWidget(lbl)

    def load_settings(self, settings: dict) -> None:
        """Stub — full implementation in Plan 3.3."""
        pass
