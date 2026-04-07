"""Central coordinator for the ASM Generator GUI.

Connects InputPage → GeneratorWorker → DiffReviewPage → export pipeline.
Instantiated once by MainWindow and passed into all three page constructors.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QWidget

from qfluentwidgets import MessageBox

from asm_generator import GeneratorConfig, GeneratorResult
from diff_engine import compute_diff
from snapshot_store import load_snapshot, save_snapshot
from settings_store import SettingsStore
from gui.workers import GeneratorWorker


class AppController:
    def __init__(self, main_window: QWidget) -> None:
        self._window = main_window
        self._settings = SettingsStore.load()
        self._last_result: GeneratorResult | None = None

        # Page references — set after pages are created (call set_pages())
        self._input_page = None
        self._diff_page = None
        self._settings_page = None

    def set_pages(self, input_page, diff_page, settings_page) -> None:
        """Called by MainWindow after all pages are instantiated."""
        self._input_page = input_page
        self._diff_page = diff_page
        self._settings_page = settings_page

        # Wire signals (connected on main thread — safe for cross-thread signals)
        input_page.run_requested.connect(self._on_run_requested)
        diff_page.export_requested.connect(self.export_zip)

        # Restore last paths on InputPage
        input_page.restore_paths(
            self._settings.get("last_student_paths", []),
            self._settings.get("last_teacher_paths", []),
            self._settings.get("last_export_paths", []),
        )

        # Apply settings to SettingsPage fields (stub accepts call gracefully)
        settings_page.load_settings(self._settings)

    def get_settings(self) -> dict:
        return self._settings

    def reload_settings(self) -> None:
        """Called by SettingsPage after save; refreshes in-memory settings."""
        self._settings = SettingsStore.load()

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
        )

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_run_requested(
        self,
        student_paths: list[str],
        teacher_paths: list[str],
        export_paths: list[str],
    ) -> None:
        """Triggered by InputPage.run_requested signal."""
        # Persist paths
        self._settings["last_student_paths"] = student_paths
        self._settings["last_teacher_paths"] = teacher_paths
        self._settings["last_export_paths"] = export_paths
        SettingsStore.save(self._settings)

        config = self.build_config()
        worker = GeneratorWorker(config, student_paths, teacher_paths, export_paths)
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

        # Build GeneratorResult from approved (checkbox-filtered) records
        approved = self._diff_page.get_approved_records()
        result = GeneratorResult(
            students=approved["students"],
            staff=approved["staff"],
            courses=approved["courses"],
            classes=approved["classes"],
            rosters=approved["rosters"],
            warnings=self._last_result.warnings if self._last_result else [],
        )

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
        try:
            write_to_zip(result, path)
        except Exception as exc:
            if os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            if isinstance(exc, PermissionError):
                detail = (
                    f"Permission denied — the file could not be written.\n\n"
                    f"{path}\n\nMake sure the file is not open in another program."
                )
            else:
                detail = str(exc)
            box = MessageBox("Export Failed", detail, self._window)
            box.exec()
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
