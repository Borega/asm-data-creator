from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt


class InputPage(QWidget):
    """Stub input page — file pickers implemented in Phase 3."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("input-page")   # REQUIRED: must be set before addSubInterface
        lbl = QLabel("Input — Coming soon", self)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.addWidget(lbl)
