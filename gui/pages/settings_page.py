"""Settings page — persistent configuration form."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    HorizontalSeparator,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

from settings_store import SettingsStore
from sftp_client import SFTP_HOST, SFTP_PORT

if TYPE_CHECKING:
    from gui.app_controller import AppController


class SettingsPage(QWidget):
    _FIELD_HEIGHT = 36
    _STATUS_MESSAGE_MAX_CHARS = 180

    def __init__(self, controller: AppController | None = None, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SettingsPage")   # Must be set before addSubInterface

        self._controller = controller
        self._init_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(16)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ---- Configuration section ----
        config_heading = SubtitleLabel("Configuration")
        root.addWidget(config_heading)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(12)
        form.setContentsMargins(0, 0, 0, 0)

        # LOCATION_ID
        self._location_id_edit = LineEdit()
        self._location_id_edit.setFixedHeight(self._FIELD_HEIGHT)
        self._location_id_edit.setPlaceholderText("e.g. LOC001")
        form.addRow(BodyLabel("Location ID"), self._location_id_edit)

        # EMAIL_DOMAIN
        self._email_domain_edit = LineEdit()
        self._email_domain_edit.setFixedHeight(self._FIELD_HEIGHT)
        self._email_domain_edit.setPlaceholderText("e.g. school.example")
        form.addRow(BodyLabel("Email Domain"), self._email_domain_edit)

        # Target school year (used for monolith mode filtering)
        self._target_year_edit = LineEdit()
        self._target_year_edit.setFixedHeight(self._FIELD_HEIGHT)
        self._target_year_edit.setPlaceholderText("e.g. 2025/2026")
        form.addRow(BodyLabel("Target School Year"), self._target_year_edit)

        # Teacher aliases path
        teacher_aliases_row = self._make_file_row(
            "_teacher_aliases_edit",
            self._browse_teacher_aliases,
        )
        form.addRow(BodyLabel("Teacher Aliases"), teacher_aliases_row)

        # Subject map path
        subject_map_row = self._make_file_row(
            "_subject_map_edit",
            self._browse_subject_map,
        )
        form.addRow(BodyLabel("Subject Map"), subject_map_row)

        root.addLayout(form)
        root.addSpacing(8)

        # Save button
        self._save_btn = PrimaryPushButton("Save Settings")
        self._save_btn.setFixedHeight(self._FIELD_HEIGHT)
        self._save_btn.clicked.connect(self._on_save_clicked)
        root.addWidget(self._save_btn)

        root.addSpacing(16)
        root.addWidget(HorizontalSeparator())
        root.addSpacing(16)

        # ---- SFTP section ----
        sftp_heading = SubtitleLabel("SFTP Upload")
        root.addWidget(sftp_heading)

        sftp_form = QFormLayout()
        sftp_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        sftp_form.setSpacing(12)
        sftp_form.setContentsMargins(0, 0, 0, 0)

        self._sftp_host_edit = LineEdit()
        self._sftp_host_edit.setFixedHeight(self._FIELD_HEIGHT)
        self._sftp_host_edit.setText(SFTP_HOST)
        self._sftp_host_edit.setReadOnly(True)
        sftp_form.addRow(BodyLabel("Hostname"), self._sftp_host_edit)

        self._sftp_port_edit = LineEdit()
        self._sftp_port_edit.setFixedHeight(self._FIELD_HEIGHT)
        self._sftp_port_edit.setText(str(SFTP_PORT))
        self._sftp_port_edit.setReadOnly(True)
        sftp_form.addRow(BodyLabel("Port"), self._sftp_port_edit)

        self._sftp_user_edit = LineEdit()
        self._sftp_user_edit.setFixedHeight(self._FIELD_HEIGHT)
        self._sftp_user_edit.setPlaceholderText("username")
        sftp_form.addRow(BodyLabel("Username"), self._sftp_user_edit)

        self._sftp_password_edit = LineEdit()
        self._sftp_password_edit.setFixedHeight(self._FIELD_HEIGHT)
        self._sftp_password_edit.setPlaceholderText("Leave empty to keep existing password")
        self._sftp_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        sftp_form.addRow(BodyLabel("Password"), self._sftp_password_edit)

        root.addLayout(sftp_form)
        root.addSpacing(8)

        self._test_sftp_btn = PushButton("Test SFTP Connection")
        self._test_sftp_btn.setFixedHeight(self._FIELD_HEIGHT)
        self._test_sftp_btn.clicked.connect(self._on_test_sftp_clicked)
        root.addWidget(self._test_sftp_btn)

        self._sftp_status_label = BodyLabel("Status: Not checked")
        self._sftp_status_label.setWordWrap(False)
        self._sftp_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._sftp_status_label.setFixedHeight(24)
        self._sftp_status_label.setToolTip("Status: Not checked")
        root.addWidget(self._sftp_status_label)

        self._analyze_activity_btn = PushButton("Analyze Activity Log")
        self._analyze_activity_btn.setFixedHeight(self._FIELD_HEIGHT)
        self._analyze_activity_btn.clicked.connect(self._on_analyze_activity_log_clicked)
        root.addWidget(self._analyze_activity_btn)

        self._set_activity_log_baseline_btn = PushButton("Use Activity Log as Diff Baseline")
        self._set_activity_log_baseline_btn.setFixedHeight(self._FIELD_HEIGHT)
        self._set_activity_log_baseline_btn.clicked.connect(self._on_set_activity_log_baseline_clicked)
        root.addWidget(self._set_activity_log_baseline_btn)

        self._set_csv_baseline_btn = PushButton("Use CSV/ZIP/Monolith as Diff Baseline")
        self._set_csv_baseline_btn.setFixedHeight(self._FIELD_HEIGHT)
        self._set_csv_baseline_btn.clicked.connect(self._on_set_csv_baseline_clicked)
        root.addWidget(self._set_csv_baseline_btn)

        self._set_last_export_baseline_btn = PushButton("Use Last Export as Diff Baseline")
        self._set_last_export_baseline_btn.setFixedHeight(self._FIELD_HEIGHT)
        self._set_last_export_baseline_btn.clicked.connect(self._on_set_last_export_baseline_clicked)
        root.addWidget(self._set_last_export_baseline_btn)

        self._clear_diff_baseline_btn = PushButton("Clear Diff Baseline")
        self._clear_diff_baseline_btn.setFixedHeight(self._FIELD_HEIGHT)
        self._clear_diff_baseline_btn.clicked.connect(self._on_clear_diff_baseline_clicked)
        root.addWidget(self._clear_diff_baseline_btn)

        self._diff_baseline_label = BodyLabel("Diff baseline: Snapshot only")
        self._diff_baseline_label.setWordWrap(True)
        root.addWidget(self._diff_baseline_label)

        root.addStretch()

    def _make_file_row(self, edit_attr: str, browse_cb) -> QWidget:
        """Build a QHBoxLayout row with a LineEdit + Browse button."""
        container = QWidget()
        container.setMinimumHeight(self._FIELD_HEIGHT)
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        edit = LineEdit()
        edit.setFixedHeight(self._FIELD_HEIGHT)
        edit.setPlaceholderText("Leave empty to use bundled default")
        setattr(self, edit_attr, edit)
        row.addWidget(edit, stretch=1)

        btn = PushButton("Browse…")
        btn.setFixedHeight(self._FIELD_HEIGHT)
        btn.clicked.connect(browse_cb)
        row.addWidget(btn)
        return container

    # ------------------------------------------------------------------
    # Browse handlers
    # ------------------------------------------------------------------

    def _browse_teacher_aliases(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select teacher_aliases.json", "", "JSON Files (*.json);;All Files (*)"
        )
        if path:
            self._teacher_aliases_edit.setText(path)

    def _browse_subject_map(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select subject_map.json", "", "JSON Files (*.json);;All Files (*)"
        )
        if path:
            self._subject_map_edit.setText(path)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _on_save_clicked(self) -> None:
        # Read current settings from disk (to preserve last_*_paths keys)
        existing = SettingsStore.load()
        old_sftp_username = existing.get("sftp_username", "")
        existing["location_id"] = self._location_id_edit.text().strip()
        existing["email_domain"] = self._email_domain_edit.text().strip()
        existing["target_school_year"] = self._target_year_edit.text().strip()
        existing["teacher_aliases_path"] = self._teacher_aliases_edit.text().strip()
        existing["subject_map_path"] = self._subject_map_edit.text().strip()
        existing["sftp_username"] = self._sftp_user_edit.text().strip()

        password = self._sftp_password_edit.text()
        new_username = existing["sftp_username"]

        # Refresh in-memory settings in AppController and update secure credentials.
        status = ""
        if self._controller is not None:
            ok, status = self._controller.save_sftp_credentials(
                old_sftp_username,
                new_username,
                password,
            )
            if not ok:
                self._show_error(status)
                return

        SettingsStore.save(existing)

        if self._controller is not None:
            self._controller.reload_settings()

        self._sftp_password_edit.clear()

        # InfoBar.success at bottom of window — auto-dismisses after 3 s
        parent_window = self.window()
        try:
            InfoBar.success(
                title="Saved",
                content=(
                    "Settings saved." if not status else f"Settings saved. SFTP status: {status}"
                ),
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.BOTTOM,
                duration=3000,
                parent=parent_window,
            )
        except TypeError:
            # Fallback for older qfluentwidgets versions with different signature
            InfoBar.success(
                title="Saved",
                content="Settings saved.",
                parent=parent_window,
            )

    def _show_error(self, message: str) -> None:
        parent_window = self.window()
        try:
            InfoBar.error(
                title="Save Failed",
                content=message,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.BOTTOM,
                duration=5000,
                parent=parent_window,
            )
        except TypeError:
            InfoBar.error(
                title="Save Failed",
                content=message,
                parent=parent_window,
            )

    def _on_test_sftp_clicked(self) -> None:
        if self._controller is None:
            return

        username = self._sftp_user_edit.text().strip()
        password_override = self._sftp_password_edit.text()
        ok, message = self._controller.test_sftp_connection(username, password_override)
        self.set_sftp_status(ok, message)

        parent_window = self.window()
        if ok:
            try:
                InfoBar.success(
                    title="SFTP Test Successful",
                    content=message,
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.BOTTOM,
                    duration=3000,
                    parent=parent_window,
                )
            except TypeError:
                InfoBar.success(
                    title="SFTP Test Successful",
                    content=message,
                    parent=parent_window,
                )
        else:
            try:
                InfoBar.warning(
                    title="SFTP Test Failed",
                    content=message,
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.BOTTOM,
                    duration=5000,
                    parent=parent_window,
                )
            except TypeError:
                InfoBar.warning(
                    title="SFTP Test Failed",
                    content=message,
                    parent=parent_window,
                )

    def _on_analyze_activity_log_clicked(self) -> None:
        if self._controller is None:
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ASM Activity Log",
            "",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        ok, report = self._controller.analyze_activity_log(path)
        title = "Activity Log Summary" if ok else "Activity Log Analysis Failed"
        self._show_activity_report_dialog(title, report)

    def _on_set_activity_log_baseline_clicked(self) -> None:
        if self._controller is None:
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ASM Activity Log for Diff Baseline",
            "",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        ok, message = self._controller.set_diff_baseline_from_activity_log(path)
        self._refresh_diff_baseline_label()
        if ok:
            self._show_info("Diff baseline updated", message)
        else:
            self._show_error(message)

    def _on_set_csv_baseline_clicked(self) -> None:
        if self._controller is None:
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select CSV, ZIP, or Benutzer-Daten CSV for Diff Baseline",
            "",
            "CSV/ZIP Files (*.csv *.zip);;All Files (*)",
        )
        if not path:
            return

        ok, message = self._controller.set_diff_baseline_from_csv(path)
        self._refresh_diff_baseline_label()
        if ok:
            self._show_info("Diff baseline updated", message)
        else:
            self._show_error(message)

    def _on_set_last_export_baseline_clicked(self) -> None:
        if self._controller is None:
            return

        ok, message = self._controller.set_diff_baseline_from_last_export()
        self._refresh_diff_baseline_label()
        if ok:
            self._show_info("Diff baseline updated", message)
        else:
            self._show_error(message)

    def _on_clear_diff_baseline_clicked(self) -> None:
        if self._controller is None:
            return

        _ok, message = self._controller.clear_diff_baseline()
        self._refresh_diff_baseline_label()
        self._show_info("Diff baseline cleared", message)

    def _refresh_diff_baseline_label(self) -> None:
        if self._controller is None:
            self._diff_baseline_label.setText("Diff baseline: Snapshot only")
            self._diff_baseline_label.setToolTip("Diff baseline: Snapshot only")
            return

        mode, path = self._controller.get_diff_baseline_config()
        if mode == "activity_log" and path:
            text = f"Diff baseline: Activity Log ({Path(path).name})"
            self._diff_baseline_label.setText(text)
            self._diff_baseline_label.setToolTip(path)
            return
        if mode == "csv" and path:
            text = f"Diff baseline: CSV/ZIP ({Path(path).name})"
            self._diff_baseline_label.setText(text)
            self._diff_baseline_label.setToolTip(path)
            return

        self._diff_baseline_label.setText("Diff baseline: Snapshot only")
        self._diff_baseline_label.setToolTip("Diff baseline: Snapshot only")

    def _show_info(self, title: str, message: str) -> None:
        parent_window = self.window()
        try:
            InfoBar.success(
                title=title,
                content=message,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.BOTTOM,
                duration=4000,
                parent=parent_window,
            )
        except TypeError:
            InfoBar.success(
                title=title,
                content=message,
                parent=parent_window,
            )

    def _show_activity_report_dialog(self, title: str, report: str) -> None:
        from PyQt6.QtWidgets import QDialog

        dialog = QDialog(self.window())
        dialog.setModal(True)
        dialog.setWindowTitle(title)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        report_view = QPlainTextEdit(dialog)
        report_view.setReadOnly(True)
        report_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        report_view.setPlainText(report)
        layout.addWidget(report_view, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_btn = PushButton("Close")
        close_btn.setFixedHeight(self._FIELD_HEIGHT)
        close_btn.clicked.connect(dialog.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        screen = self.window().screen() if self.window() is not None else QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            max_width = max(360, available.width() - 40)
            max_height = max(280, available.height() - 40)
            preferred_width = max(680, int(available.width() * 0.8))
            preferred_height = max(420, int(available.height() * 0.8))
            dialog.resize(min(preferred_width, max_width), min(preferred_height, max_height))
            dialog.move(available.center() - dialog.rect().center())
        else:
            dialog.resize(900, 640)

        dialog.exec()

    @staticmethod
    def _compact_status_message(message: str, max_chars: int) -> str:
        compact = " ".join((message or "").split())
        if len(compact) <= max_chars:
            return compact
        return f"{compact[: max_chars - 1].rstrip()}…"

    def set_sftp_status(self, ok: bool, message: str) -> None:
        state = "Connected" if ok else "Not ready"
        compact_message = self._compact_status_message(message, self._STATUS_MESSAGE_MAX_CHARS)
        if compact_message:
            self._sftp_status_label.setText(f"Status: {state} - {compact_message}")
            self._sftp_status_label.setToolTip(f"Status: {state} - {' '.join((message or '').split())}")
        else:
            self._sftp_status_label.setText(f"Status: {state}")
            self._sftp_status_label.setToolTip(f"Status: {state}")

    # ------------------------------------------------------------------
    # Public API (called by AppController.set_pages)
    # ------------------------------------------------------------------

    def load_settings(self, settings: dict) -> None:
        """Populate form fields from a settings dict (e.g. loaded from SettingsStore)."""
        self._location_id_edit.setText(settings.get("location_id", ""))
        self._email_domain_edit.setText(settings.get("email_domain", ""))
        self._target_year_edit.setText(settings.get("target_school_year", ""))
        self._teacher_aliases_edit.setText(settings.get("teacher_aliases_path", ""))
        self._subject_map_edit.setText(settings.get("subject_map_path", ""))
        self._sftp_host_edit.setText(SFTP_HOST)
        self._sftp_port_edit.setText(str(SFTP_PORT))
        self._sftp_user_edit.setText(settings.get("sftp_username", ""))
        self._sftp_password_edit.clear()

        if self._controller is not None:
            ok, msg = self._controller.get_sftp_status()
            self.set_sftp_status(ok, msg)

        self._refresh_diff_baseline_label()
