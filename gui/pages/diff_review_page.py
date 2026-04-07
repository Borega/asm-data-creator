from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt


class DiffReviewPage(QWidget):
    """Stub diff review page — color-coded table implemented in Phase 3."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("diff-review-page")   # REQUIRED
        lbl = QLabel("Diff Review — Coming soon", self)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.addWidget(lbl)
