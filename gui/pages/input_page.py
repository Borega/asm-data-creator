"""Input page — file pickers and Run button."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    HorizontalSeparator,
    IndeterminateProgressRing,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

if TYPE_CHECKING:
    from gui.app_controller import AppController


class InputPage(QWidget):
    # Payload: (student_paths, teacher_paths, export_paths) — all list[str]
    run_requested = pyqtSignal(list, list, list)

    def __init__(self, controller: "AppController | None" = None, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("InputPage")   # MUST be first statement — qfluentwidgets router requirement

        self._controller = controller

        # State storage
        self._student_paths: list[str] = []
        self._teacher_paths: list[str] = []
        self._export_paths: list[str] = []
        # Per-slot export paths (two independent pickers merged into one list)
        self._export_slot_0: list[str] = []
        self._export_slot_1: list[str] = []

        self._init_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(16)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Section heading
        heading = SubtitleLabel("Input Files")
        root.addWidget(heading)

        # --- File picker rows ---

        # Students
        self._student_label = BodyLabel("No file selected")
        root.addLayout(
            self._make_picker_row("Students", self._student_label, self._browse_students)
        )

        # Teachers (existing staff.csv for email carry-forward)
        self._teacher_label = BodyLabel("No file selected")
        root.addLayout(
            self._make_picker_row("Teachers", self._teacher_label, self._browse_teachers)
        )

        # Course Export 1
        self._export1_label = BodyLabel("No file selected")
        root.addLayout(
            self._make_picker_row("Course Export 1", self._export1_label, self._browse_export1)
        )

        # Course Export 2
        self._export2_label = BodyLabel("No file selected")
        root.addLayout(
            self._make_picker_row("Course Export 2", self._export2_label, self._browse_export2)
        )

        root.addSpacing(8)
        root.addWidget(HorizontalSeparator())
        root.addSpacing(8)

        # --- Run section ---
        run_layout = QVBoxLayout()
        run_layout.setSpacing(8)
        run_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._run_btn = PrimaryPushButton(FIF.PLAY, "Run")
        self._run_btn.setMinimumHeight(36)
        self._run_btn.clicked.connect(self._on_run_clicked)
        run_layout.addWidget(self._run_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._spinner = IndeterminateProgressRing()
        self._spinner.setFixedSize(32, 32)
        self._spinner.hide()
        run_layout.addWidget(self._spinner, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._status_label = CaptionLabel("Ready")
        run_layout.addWidget(self._status_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        root.addLayout(run_layout)
        root.addStretch()

    @staticmethod
    def _make_picker_row(label_text: str, path_label: BodyLabel, callback) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        name_lbl = BodyLabel(label_text)
        name_lbl.setFixedWidth(120)
        browse_btn = PushButton("Browse…")
        browse_btn.clicked.connect(callback)
        row.addWidget(name_lbl)
        row.addWidget(path_label, stretch=1)
        row.addWidget(browse_btn)
        return row

    # ------------------------------------------------------------------
    # File picker handlers
    # ------------------------------------------------------------------

    def _browse_students(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Student CSV", "", "CSV Files (*.csv *.txt);;All Files (*)"
        )
        if path:
            self._student_paths = [path]
            self._student_label.setText(path)

    def _browse_teachers(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Teacher / Staff CSV", "", "CSV Files (*.csv *.txt);;All Files (*)"
        )
        if path:
            self._teacher_paths = [path]
            self._teacher_label.setText(path)

    def _browse_export1(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Course Export CSV(s)", "", "CSV Files (*.csv);;All Files (*)"
        )
        if paths:
            self._update_export_paths(paths, slot=0)

    def _browse_export2(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Course Export CSV(s)", "", "CSV Files (*.csv);;All Files (*)"
        )
        if paths:
            self._update_export_paths(paths, slot=1)

    def _update_export_paths(self, new_paths: list[str], slot: int) -> None:
        """Maintain two independent export path slots; refresh labels."""
        if slot == 0:
            self._export_slot_0 = new_paths
            lbl = self._export1_label
        else:
            self._export_slot_1 = new_paths
            lbl = self._export2_label
        self._export_paths = self._export_slot_0 + self._export_slot_1
        if len(new_paths) == 1:
            lbl.setText(new_paths[0])
        else:
            lbl.setText(f"{len(new_paths)} files selected")

    # ------------------------------------------------------------------
    # Run logic
    # ------------------------------------------------------------------

    def _on_run_clicked(self) -> None:
        self._run_btn.setEnabled(False)
        self._spinner.show()
        self._status_label.setText("Running…")
        self.run_requested.emit(
            self._student_paths,
            self._teacher_paths,
            self._export_paths,
        )

    def on_run_complete(self) -> None:
        """Called by AppController after worker finishes successfully."""
        self._run_btn.setEnabled(True)
        self._spinner.hide()
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        self._status_label.setText(f"Last run: {now}")

    def on_run_error(self) -> None:
        """Called by AppController after worker emits error."""
        self._run_btn.setEnabled(True)
        self._spinner.hide()
        self._status_label.setText("Ready")

    # ------------------------------------------------------------------
    # Path restoration (called by AppController.set_pages)
    # ------------------------------------------------------------------

    def restore_paths(
        self,
        student_paths: list[str],
        teacher_paths: list[str],
        export_paths: list[str],
    ) -> None:
        if student_paths:
            self._student_paths = student_paths
            self._student_label.setText(
                student_paths[0] if len(student_paths) == 1 else f"{len(student_paths)} files selected"
            )
        if teacher_paths:
            self._teacher_paths = teacher_paths
            self._teacher_label.setText(
                teacher_paths[0] if len(teacher_paths) == 1 else f"{len(teacher_paths)} files selected"
            )
        if export_paths:
            self._export_paths = export_paths
            # Restore all previously saved export paths into slot 0
            self._export_slot_0 = export_paths
            self._export_slot_1 = []
            count = len(export_paths)
            self._export1_label.setText(
                export_paths[0] if count == 1 else f"{count} files selected"
            )
            self._export2_label.setText("No file selected")
