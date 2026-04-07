from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt


class DiffReviewPage(QWidget):
    """Stub diff review page — color-coded table implemented in Phase 3."""

    def __init__(self, controller=None, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("diff-review-page")   # REQUIRED
        self._controller = controller
        lbl = QLabel("Diff Review — Coming soon", self)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.addWidget(lbl)

    def load_diff(self, diff_result) -> None:
        """Stub — full implementation in Plan 3.2."""
        pass
