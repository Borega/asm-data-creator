"""Settings page — persistent configuration form."""
from __future__ import annotations
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog, QFormLayout, QHBoxLayout, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, FluentIcon as FIF, HorizontalSeparator, InfoBar, InfoBarPosition,
    LineEdit, PrimaryPushButton, PushButton, SubtitleLabel,
)

try:
    from qfluentwidgets import ToolTipFilter, ToolTipPosition
    _HAS_TOOLTIP_FILTER = True
except ImportError:
    _HAS_TOOLTIP_FILTER = False

from settings_store import SettingsStore

if TYPE_CHECKING:
    from gui.app_controller import AppController


class SettingsPage(QWidget):
    def __init__(self, controller: "AppController | None" = None, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SettingsPage")   # Must be set before addSubInterface

        self._controller = controller
        self._init_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
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
        self._location_id_edit.setMinimumHeight(32)
        self._location_id_edit.setPlaceholderText("e.g. R001")
        form.addRow(BodyLabel("Location ID"), self._location_id_edit)

        # EMAIL_DOMAIN
        self._email_domain_edit = LineEdit()
        self._email_domain_edit.setMinimumHeight(32)
        self._email_domain_edit.setPlaceholderText("e.g. schulerissen.de")
        form.addRow(BodyLabel("Email Domain"), self._email_domain_edit)

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
        self._save_btn.setMinimumHeight(36)
        self._save_btn.clicked.connect(self._on_save_clicked)
        root.addWidget(self._save_btn)

        root.addSpacing(16)
        root.addWidget(HorizontalSeparator())
        root.addSpacing(16)

        # ---- SFTP section (Coming Soon) ----
        sftp_heading = SubtitleLabel("SFTP Upload (Coming Soon)")
        root.addWidget(sftp_heading)

        sftp_form = QFormLayout()
        sftp_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        sftp_form.setSpacing(12)
        sftp_form.setContentsMargins(0, 0, 0, 0)

        self._sftp_host_edit = LineEdit()
        self._sftp_host_edit.setMinimumHeight(32)
        self._sftp_host_edit.setPlaceholderText("hostname")
        self._sftp_host_edit.setEnabled(False)
        sftp_form.addRow(BodyLabel("Hostname"), self._sftp_host_edit)

        self._sftp_user_edit = LineEdit()
        self._sftp_user_edit.setMinimumHeight(32)
        self._sftp_user_edit.setPlaceholderText("username")
        self._sftp_user_edit.setEnabled(False)
        sftp_form.addRow(BodyLabel("Username"), self._sftp_user_edit)

        root.addLayout(sftp_form)
        root.addSpacing(8)

        self._upload_btn = PrimaryPushButton(FIF.SEND, "Upload")
        self._upload_btn.setEnabled(False)
        self._upload_btn.setMinimumHeight(36)
        self._upload_btn.setToolTip("SFTP upload coming in a future version")
        if _HAS_TOOLTIP_FILTER:
            self._upload_btn.installEventFilter(
                ToolTipFilter(self._upload_btn, showDelay=300, position=ToolTipPosition.TOP)
            )
        root.addWidget(self._upload_btn)

        root.addStretch()

    def _make_file_row(self, edit_attr: str, browse_cb) -> QWidget:
        """Build a QHBoxLayout row with a LineEdit + Browse button."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        edit = LineEdit()
        edit.setMinimumHeight(32)
        edit.setPlaceholderText("Leave empty to use bundled default")
        setattr(self, edit_attr, edit)
        row.addWidget(edit, stretch=1)

        btn = PushButton("Browse…")
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
        existing["location_id"] = self._location_id_edit.text().strip()
        existing["email_domain"] = self._email_domain_edit.text().strip()
        existing["teacher_aliases_path"] = self._teacher_aliases_edit.text().strip()
        existing["subject_map_path"] = self._subject_map_edit.text().strip()

        SettingsStore.save(existing)

        # Refresh in-memory settings in AppController
        if self._controller is not None:
            self._controller.reload_settings()

        # InfoBar.success at bottom of window — auto-dismisses after 3 s
        parent_window = self.window()
        try:
            InfoBar.success(
                title="Saved",
                content="Settings saved.",
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

    # ------------------------------------------------------------------
    # Public API (called by AppController.set_pages)
    # ------------------------------------------------------------------

    def load_settings(self, settings: dict) -> None:
        """Populate form fields from a settings dict (e.g. loaded from SettingsStore)."""
        self._location_id_edit.setText(settings.get("location_id", ""))
        self._email_domain_edit.setText(settings.get("email_domain", ""))
        self._teacher_aliases_edit.setText(settings.get("teacher_aliases_path", ""))
        self._subject_map_edit.setText(settings.get("subject_map_path", ""))
