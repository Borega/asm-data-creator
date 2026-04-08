"""Central coordinator for the ASM Generator GUI.

Connects InputPage → GeneratorWorker → DiffReviewPage → export pipeline.
Instantiated once by MainWindow and passed into all three page constructors.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QWidget

from qfluentwidgets import MessageBox

from asm_generator import GeneratorConfig, GeneratorResult
from diff_engine import compute_diff
from snapshot_store import load_snapshot, save_snapshot
from settings_store import SettingsStore
from gui.workers import GeneratorWorker
from sftp_client import check_connection as check_sftp_connection, upload_file
from sftp_credentials import (
    CredentialError,
    delete_password,
    get_password,
    has_password,
    is_keyring_available,
    set_password,
)


class AppController:
    @staticmethod
    def _normalize_input_mode(mode: str) -> str:
        m = (mode or "").strip().lower()
        if m == "legacy":
            return "legacy"
        return "schuldock"

    def __init__(self, main_window: QWidget) -> None:
        self._window = main_window
        self._settings = SettingsStore.load()
        self._last_result: GeneratorResult | None = None
        self._sftp_ready = False
        self._sftp_status_message = "SFTP not configured."

        # Page references — set after pages are created (call set_pages())
        self._input_page = None
        self._diff_page = None
        self._settings_page = None

        # Validate upload capability once during startup.
        self._refresh_sftp_status(check_connection=True)

    def set_pages(self, input_page, diff_page, settings_page) -> None:
        """Called by MainWindow after all pages are instantiated."""
        self._input_page = input_page
        self._diff_page = diff_page
        self._settings_page = settings_page

        # Wire signals (connected on main thread — safe for cross-thread signals)
        input_page.run_requested.connect(self._on_run_requested)
        diff_page.export_requested.connect(self.export_zip)
        diff_page.upload_requested.connect(self.export_zip_and_upload)

        # Restore last paths on InputPage
        input_page.restore_paths(
            self._settings.get("last_student_paths", []),
            self._settings.get("last_teacher_paths", []),
            self._settings.get("last_export_paths", []),
            self._normalize_input_mode(self._settings.get("input_mode", "schuldock")),
            self._settings.get("last_monolith_paths", []),
        )

        # Apply settings to SettingsPage fields (stub accepts call gracefully)
        settings_page.load_settings(self._settings)
        self._refresh_upload_ui_state()

    def get_settings(self) -> dict:
        return self._settings

    def reload_settings(self) -> None:
        """Called by SettingsPage after save; refreshes in-memory settings."""
        self._settings = SettingsStore.load()
        self._refresh_sftp_status(check_connection=True)
        self._refresh_upload_ui_state()

    def should_open_settings_on_startup(self) -> bool:
        return not self._has_sftp_credentials()

    def save_sftp_credentials(self, old_username: str, new_username: str, password: str) -> tuple[bool, str]:
        old_username = (old_username or "").strip()
        new_username = (new_username or "").strip()
        password = password or ""

        if new_username and not is_keyring_available():
            return False, "Secure keyring backend is not available on this system."

        if old_username and old_username != new_username:
            delete_password(old_username)

        if not new_username:
            self._sftp_ready = False
            self._sftp_status_message = "Missing SFTP username."
            self._refresh_upload_ui_state()
            return True, "SFTP credentials cleared."

        try:
            if password:
                set_password(new_username, password)
            elif old_username != new_username and not has_password(new_username):
                return False, "Enter a password when changing SFTP username."
        except CredentialError as exc:
            return False, f"Could not store SFTP password securely: {exc}"

        try:
            effective_password = password or get_password(new_username)
        except CredentialError as exc:
            return False, f"Could not read SFTP password: {exc}"

        if not effective_password:
            self._sftp_ready = False
            self._sftp_status_message = "Missing SFTP password."
            self._refresh_upload_ui_state()
            return True, self._sftp_status_message

        self._sftp_ready, self._sftp_status_message = check_sftp_connection(new_username, effective_password)
        self._refresh_upload_ui_state()
        return True, self._sftp_status_message

    def get_sftp_status(self) -> tuple[bool, str]:
        return self._sftp_ready, self._sftp_status_message

    def test_sftp_connection(self, username: str, password_override: str = "") -> tuple[bool, str]:
        """Run an on-demand SFTP connection test from the Settings page."""
        user = (username or "").strip()
        if not user:
            return False, "Missing SFTP username."
        if not is_keyring_available() and not (password_override or "").strip():
            return False, "Secure keyring backend is unavailable and no password was provided."

        password = password_override or ""
        if not password:
            try:
                password = get_password(user)
            except CredentialError as exc:
                return False, f"Credential error: {exc}"

        if not password:
            return False, "Missing SFTP password."
        return check_sftp_connection(user, password)

    def _has_sftp_credentials(self) -> bool:
        username = (self._settings.get("sftp_username", "") or "").strip()
        if not username or not is_keyring_available():
            return False
        try:
            return bool(get_password(username))
        except CredentialError:
            return False

    def _refresh_sftp_status(self, check_connection: bool) -> None:
        username = (self._settings.get("sftp_username", "") or "").strip()
        if not username:
            self._sftp_ready = False
            self._sftp_status_message = "Missing SFTP username."
            return

        if not is_keyring_available():
            self._sftp_ready = False
            self._sftp_status_message = "Secure keyring backend is unavailable."
            return

        try:
            password = get_password(username)
        except CredentialError as exc:
            self._sftp_ready = False
            self._sftp_status_message = f"Credential error: {exc}"
            return

        if not password:
            self._sftp_ready = False
            self._sftp_status_message = "Missing SFTP password."
            return

        if check_connection:
            ok, msg = check_sftp_connection(username, password)
            self._sftp_ready = ok
            self._sftp_status_message = msg
        else:
            self._sftp_ready = True
            self._sftp_status_message = "SFTP credentials available."

    def _refresh_upload_ui_state(self) -> None:
        if self._diff_page is not None:
            self._diff_page.set_upload_available(self._sftp_ready, self._sftp_status_message)
        if self._settings_page is not None:
            self._settings_page.set_sftp_status(self._sftp_ready, self._sftp_status_message)

    def build_config(self) -> GeneratorConfig:
        """Build GeneratorConfig from current settings, resolving empty paths to bundled defaults."""

        def _resolve(path_str: str, filename: str) -> str:
            if path_str:
                return path_str
            # Frozen (PyInstaller): sys._MEIPASS; dev: project root
            base = getattr(sys, "_MEIPASS", Path(__file__).parent.parent)
            return str(Path(base) / filename)

        return GeneratorConfig(
            location_id=self._settings.get("location_id", ""),
            email_domain=self._settings.get("email_domain", ""),
            aliases_path=_resolve(
                self._settings.get("teacher_aliases_path", ""), "teacher_aliases.json"
            ),
            subjects_path=_resolve(
                self._settings.get("subject_map_path", ""), "subject_map.json"
            ),
            input_mode=self._settings.get("input_mode", "schuldock"),
            target_school_year=self._settings.get("target_school_year", ""),
        )

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_run_requested(
        self,
        student_paths: list[str],
        teacher_paths: list[str],
        export_paths: list[str],
        input_mode: str,
        monolith_paths: list[str],
    ) -> None:
        """Triggered by InputPage.run_requested signal."""
        # Persist paths
        self._settings["last_student_paths"] = student_paths
        self._settings["last_teacher_paths"] = teacher_paths
        self._settings["last_export_paths"] = export_paths
        mode = self._normalize_input_mode(input_mode)
        self._settings["last_monolith_paths"] = monolith_paths
        self._settings["input_mode"] = mode
        SettingsStore.save(self._settings)

        config = self.build_config()
        worker = GeneratorWorker(
            config,
            student_paths,
            teacher_paths,
            export_paths,
            input_mode=mode,
            monolith_paths=monolith_paths,
        )
        # Signals connected on main thread — safe for cross-thread delivery
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.error.connect(self._on_worker_error)
        QThreadPool.globalInstance().start(worker)

    def _on_worker_finished(self, result: GeneratorResult) -> None:
        self._last_result = result
        self._input_page.on_run_complete()  # always re-enable Run + hide spinner first

        try:
            snapshot = load_snapshot()
        except Exception as exc:  # noqa: BLE001 — includes json.JSONDecodeError
            MessageBox(
                "Snapshot Load Error",
                f"Could not read the previous snapshot (treating as first run).\n\n{exc}",
                self._window,
            ).exec()
            snapshot = None

        diff_result = compute_diff(result, snapshot)
        self._diff_page.load_diff(diff_result)
        self._diff_page.set_upload_available(self._sftp_ready, self._sftp_status_message)

        # Navigate to DiffReviewPage — MainWindow.switchTo() handles nav sync
        self._window.switchTo(self._diff_page)

    def _on_worker_error(self, message: str) -> None:
        self._input_page.on_run_error()
        box = MessageBox("Generation Failed", message, self._window)
        box.exec()

    def export_zip(self) -> None:
        """Triggered by DiffReviewPage.export_requested. Full export pipeline."""
        from PyQt6.QtWidgets import QFileDialog
        from asm_generator.writer import write_to_zip

        result = self._build_result_from_approved()

        # Ask user for output path
        path, _ = QFileDialog.getSaveFileName(
            self._window,
            "Export ASM ZIP",
            "asm_export.zip",
            "ZIP Files (*.zip)",
        )
        if not path:
            return  # User cancelled

        # Write ZIP — handle errors before saving snapshot
        if not self._write_zip_or_show_error(result, path, write_to_zip):
            return

        # Save snapshot only after successful ZIP write
        save_snapshot(result)

        # Notify user, then reset diff page to placeholder
        box = MessageBox(
            "Export Successful",
            f"The ASM ZIP was exported successfully.\n\n{path}",
            self._window,
        )
        box.exec()
        self._diff_page.reset()

    def export_zip_and_upload(self) -> None:
        """Create a ZIP in temp storage, upload via SFTP, then persist snapshot."""
        from asm_generator.writer import write_to_zip

        if not self._sftp_ready:
            box = MessageBox(
                "SFTP Not Ready",
                f"Upload is disabled because startup validation failed.\n\n{self._sftp_status_message}",
                self._window,
            )
            box.exec()
            return

        username = (self._settings.get("sftp_username", "") or "").strip()
        try:
            password = get_password(username)
        except CredentialError as exc:
            box = MessageBox("Credential Error", str(exc), self._window)
            box.exec()
            return

        if not username or not password:
            box = MessageBox(
                "Missing Credentials",
                "Please configure SFTP username and password in Settings.",
                self._window,
            )
            box.exec()
            return

        result = self._build_result_from_approved()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        with tempfile.TemporaryDirectory(prefix="asm-upload-") as tmp_dir:
            zip_path = Path(tmp_dir) / f"asm_export_{timestamp}.zip"
            if not self._write_zip_or_show_error(result, str(zip_path), write_to_zip):
                return

            try:
                remote_name = upload_file(zip_path, username=username, password=password)
            except Exception as exc:  # noqa: BLE001
                box = MessageBox("Upload Failed", str(exc), self._window)
                box.exec()
                return

        save_snapshot(result)

        box = MessageBox(
            "Upload Successful",
            (
                "ZIP was created and uploaded successfully.\n\n"
                f"Host: upload.appleschoolcontent.com:22\n"
                f"Remote file: {remote_name}"
            ),
            self._window,
        )
        box.exec()
        self._diff_page.reset()

    def _build_result_from_approved(self) -> GeneratorResult:
        approved = self._diff_page.get_approved_records()
        return GeneratorResult(
            students=approved["students"],
            staff=approved["staff"],
            courses=approved["courses"],
            classes=approved["classes"],
            rosters=approved["rosters"],
            warnings=self._last_result.warnings if self._last_result else [],
        )

    def _write_zip_or_show_error(self, result: GeneratorResult, path: str, write_to_zip) -> bool:
        try:
            write_to_zip(result, path)
            return True
        except Exception as exc:  # noqa: BLE001
            if os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            if isinstance(exc, PermissionError):
                detail = (
                    "Permission denied - the file could not be written.\n\n"
                    f"{path}\n\nMake sure the file is not open in another program."
                )
            else:
                detail = str(exc)
            box = MessageBox("Export Failed", detail, self._window)
            box.exec()
            return False
