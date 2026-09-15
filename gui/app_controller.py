"""Central coordinator for the ASM Generator GUI.

Connects InputPage → GeneratorWorker → DiffReviewPage → export pipeline.
Instantiated once by MainWindow and passed into all three page constructors.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtWidgets import QApplication, QProgressDialog, QWidget
from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox, PushButton

import update_check

from activity_log import (
    extract_baseline_from_activity_log,
    load_person_state,
    render_activity_log_summary,
    summarize_activity_log,
)
from asm_generator import GeneratorConfig, GeneratorResult
from asm_state import AsmState
from backup_store import create_backup
from diff_baseline import load_baseline_from_csv_source
from diff_engine import compute_diff
import person_pins
from gui.workers import (
    GeneratorWorker,
    SftpStatusWorker,
    UpdateCheckWorker,
    UpdateInstallWorker,
)
from settings_store import SettingsStore
from sftp_client import check_connection as check_sftp_connection
from sftp_client import upload_file
from sftp_credentials import (
    CredentialError,
    delete_password,
    get_password,
    has_password,
    is_keyring_available,
    set_password,
)
from snapshot_store import load_provenance, load_snapshot, save_snapshot

logger = logging.getLogger(__name__)


_MAX_NOTE_LINES = 4        # per category — a wall of text hides the headline
_MAX_REVIEW_NOTES = 10
_MAX_NAMES_PER_LINE = 5


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _looks_like_uuid(value: str) -> bool:
    """Distinguishes a SIS-id person_id from a name-derived one."""
    return bool(_UUID_RE.match((value or "").strip()))


def _staff_key_scheme(rows: list) -> str:
    """Which scheme these staff ids follow: 'uuid', 'name', or 'unknown'.

    Judged by majority, not by a sample: even in interne_id mode a roster is
    legitimately mixed, because a teacher who appears only in a course export
    has no SIS id and falls back to a name-derived one. Reading one row would
    make the answer depend on list order.
    """
    ids = [(row.get("person_id") or "").strip() for row in rows]
    ids = [pid for pid in ids if pid]
    if not ids:
        return "unknown"
    uuids = sum(1 for pid in ids if _looks_like_uuid(pid))
    names = len(ids) - uuids
    if uuids > names:
        return "uuid"
    if names > uuids:
        return "name"
    return "unknown"


def _person_label(record: dict | None, person_id: str) -> str:
    """'Anna Meier (anna.meier)', or just the id when the record is unknown."""
    if not record:
        return person_id
    name = " ".join(
        p for p in (record.get("first_name", ""), record.get("last_name", "")) if p
    ).strip()
    return f"{name} ({person_id})" if name else person_id


def _summarise(items: list[str]) -> str:
    head = ", ".join(items[:_MAX_NAMES_PER_LINE])
    extra = len(items) - _MAX_NAMES_PER_LINE
    return f"{head} and {extra:,} more" if extra > 0 else head


def _cap(lines: list[str]) -> list[str]:
    """Capped per category, so a long list in one never hides another."""
    extra = len(lines) - _MAX_NOTE_LINES
    return lines if extra <= 0 else lines[:_MAX_NOTE_LINES] + [f"…and {extra:,} more"]


def _prune_dangling_references(
    result: GeneratorResult,
    catalogue: GeneratorResult | None = None,
) -> list[str]:
    """Drop rows pointing at a person or class this export is holding back.

    Unticking an ADDED row keeps that record out of the file, but the rows that
    referenced it stay behind: a class still names the teacher as instructor, a
    roster still names the student. ASM rejects a file whose foreign keys point
    at nothing, so an unticked row would fail the whole upload rather than the
    one record.

    *catalogue* is the unfiltered result, used only to turn the ids of dropped
    records back into names — the whole point of the report is to say who, and
    by this stage the held-back rows are gone from *result* itself.

    Mutates *result* in place and returns human-readable notes, capped so a
    large prune stays readable.
    """
    # Falls back to result when no usable catalogue is supplied: the report then
    # names ids instead of people, which is worse but never fatal.
    ref = catalogue if isinstance(catalogue, GeneratorResult) else result
    staff_by_id = {s.get("person_id"): s for s in ref.staff}
    students_by_id = {s.get("person_id"): s for s in ref.students}
    class_label = {
        c.get("class_id"): (c.get("class_number") or c.get("class_id"))
        for c in ref.classes
    }
    course_label = {
        c.get("course_id"): (c.get("course_name") or c.get("course_number") or c.get("course_id"))
        for c in ref.courses
    }

    course_notes: list[str] = []
    student_notes: list[str] = []
    teacher_notes: list[str] = []

    live_courses = {c.get("course_id") for c in result.courses}
    dropped_classes = [c for c in result.classes if c.get("course_id") not in live_courses]
    if dropped_classes:
        result.classes = [c for c in result.classes if c.get("course_id") in live_courses]
        by_course: dict[str, list[str]] = {}
        for cls in dropped_classes:
            by_course.setdefault(cls.get("course_id"), []).append(
                class_label.get(cls.get("class_id"), cls.get("class_id", "?"))
            )
        for course_id, names in by_course.items():
            course_notes.append(
                f"Course not being created: {course_label.get(course_id, course_id)} "
                f"— dropped {len(names):,} class(es): {_summarise(names)}"
            )

    live_classes = {c.get("class_id") for c in result.classes}
    live_students = {s.get("person_id") for s in result.students}
    kept, lost = [], []
    for roster in result.rosters:
        if roster.get("class_id") in live_classes and roster.get("student_id") in live_students:
            kept.append(roster)
        else:
            lost.append(roster)
    if lost:
        result.rosters = kept
        by_student: dict[str, int] = {}
        for roster in lost:
            sid = roster.get("student_id")
            if sid not in live_students:
                by_student[sid] = by_student.get(sid, 0) + 1
        for sid, count in by_student.items():
            student_notes.append(
                f"Student not being created: {_person_label(students_by_id.get(sid), sid)} "
                f"— removed {count:,} enrolment(s)"
            )
        orphaned = len(lost) - sum(by_student.values())
        if orphaned:
            course_notes.append(
                f"{orphaned:,} further enrolment(s) removed for dropped classes")

    # An instructor is optional on a class, so blank the reference rather than
    # dropping the class and everyone enrolled in it.
    live_staff = {s.get("person_id") for s in result.staff}
    by_teacher: dict[str, list[str]] = {}
    for cls in result.classes:
        for field_name in ("instructor_id", "instructor_id_2", "instructor_id_3"):
            pid = cls.get(field_name)
            if pid and pid not in live_staff:
                cls[field_name] = ""
                by_teacher.setdefault(pid, []).append(
                    class_label.get(cls.get("class_id"), cls.get("class_id", "?"))
                )
    for pid, class_names in by_teacher.items():
        teacher_notes.append(
            f"Teacher not being created: {_person_label(staff_by_id.get(pid), pid)} "
            f"— removed as instructor from {len(class_names):,} class(es): "
            f"{_summarise(class_names)}"
        )

    # Most destructive first: a dropped course takes whole classes with it, a
    # missing teacher only empties a field, a missing student only their own rows.
    return _cap(course_notes) + _cap(teacher_notes) + _cap(student_notes)


class AppController:
    SFTP_CHECK_PENDING_MESSAGE = "Checking SFTP connection…"

    @staticmethod
    def _normalize_input_mode(mode: str) -> str:
        m = (mode or "").strip().lower()
        if m == "legacy":
            return "legacy"
        return "schuldock"

    @staticmethod
    def _normalize_diff_baseline_mode(mode: str) -> str:
        m = (mode or "").strip().lower()
        if m in {"snapshot", "activity_log", "csv"}:
            return m
        return "snapshot"

    @staticmethod
    def _normalize_sftp_check_result(result: object) -> tuple[bool, str]:
        """Defensively coerce SFTP check output to the controller contract."""
        if isinstance(result, tuple) and len(result) == 2:
            ready, message = result
            normalized_message = str(message or "Unexpected SFTP connection response.")
            return ready is True, normalized_message
        return False, "Unexpected SFTP connection response."

    @staticmethod
    def _classify_upload_exception(exc: Exception) -> dict[str, str | bool]:
        """Classify upload failures into stable user copy + diagnostics tags."""
        message = str(exc or "").strip()
        lowered = message.lower()

        if "authentication failed" in lowered:
            return {
                "title": "Upload Authentication Failed",
                "body": (
                    "The upload server rejected the credentials. Please check SFTP "
                    "username/password in Settings.\n\n"
                    "Retry to attempt the upload again, or Cancel to stop."
                ),
                "category": "auth",
                "retryable": True,
            }

        if "upload interrupted" in lowered or "connection timed out" in lowered or "dns resolution failed" in lowered:
            return {
                "title": "Upload Interrupted",
                "body": (
                    "The upload was interrupted by a network issue.\n\n"
                    "Retry to continue with the same ZIP, or Cancel to stop."
                ),
                "category": "interruption",
                "retryable": True,
            }

        return {
            "title": "Upload Failed",
            "body": message or "The upload failed due to an unexpected error.",
            "category": "unknown",
            "retryable": False,
        }

    def __init__(self, main_window: QWidget) -> None:
        self._window = main_window
        self._settings = SettingsStore.load()
        self._last_result: GeneratorResult | None = None
        self._sftp_ready = False
        self._sftp_status_message = "SFTP not configured."
        self._sftp_check_token = 0
        self._sftp_recheck_pending = False  # set by save_sftp_credentials, run by reload_settings

        # Page references — set after pages are created (call set_pages())
        self._input_page = None
        self._diff_page = None
        self._settings_page = None

        # Validate upload capability once during startup — off the GUI thread so
        # an unreachable SFTP host cannot delay the window appearing.
        self._start_sftp_status_check()

        self._update_release = None
        self._update_message = "Not checked yet."
        self._update_check_token = 0
        self._update_worker = None  # keeps the running install worker alive
        self._update_progress = None
        if self._settings.get("check_for_updates", True):
            self.start_update_check()

    def set_pages(self, input_page, diff_page, settings_page) -> None:
        """Called by MainWindow after all pages are instantiated."""
        self._input_page = input_page
        self._diff_page = diff_page
        self._settings_page = settings_page

        input_page.refresh_setup_hint()

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
        """Called by SettingsPage after save; refreshes in-memory settings.

        Re-checks the SFTP connection only when Save changed the credentials,
        and then off the GUI thread: a blocking probe on Save once froze the
        window for the full timeout on an unreachable host. It runs here rather
        than in save_sftp_credentials because only now is the new username in
        the settings the probe reads.
        """
        self._settings = SettingsStore.load()
        if self._sftp_recheck_pending:
            self._sftp_recheck_pending = False
            self._start_sftp_status_check()
        else:
            self._refresh_upload_ui_state()
        if self._input_page is not None:
            self._input_page.refresh_setup_hint()

    # Settings that generation cannot proceed without, and the labels the
    # Settings page shows for them, so a message can name the field to fill.
    REQUIRED_SETTINGS = (
        ("location_id", "Location ID"),
        ("email_domain", "Email Domain"),
    )

    def missing_required_settings(self) -> list[str]:
        """Labels of required settings still blank. Empty means ready to run.

        Without this a fresh install gets as far as choosing input files before
        failing, and the reason arrives as a generator exception rather than as
        the name of the field to fill in.
        """
        return [
            label for key, label in self.REQUIRED_SETTINGS
            if not (self._settings.get(key, "") or "").strip()
        ]

    def should_open_settings_on_startup(self) -> bool:
        return bool(self.missing_required_settings()) or not self._has_sftp_credentials()

    def save_sftp_credentials(self, old_username: str, new_username: str, password: str) -> tuple[bool, str]:
        # The user is changing credentials — retire any probe still in flight.
        self._sftp_check_token += 1
        old_username = (old_username or "").strip()
        new_username = (new_username or "").strip()
        password = password or ""

        if new_username and not is_keyring_available():
            return False, "Secure keyring backend is not available on this system."

        if not new_username:
            if old_username:
                delete_password(old_username)
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

        # Only now that the new password is stored is the old one retired, so a
        # failed change never leaves the school without a working password.
        if old_username and old_username != new_username:
            delete_password(old_username)

        try:
            effective_password = password or get_password(new_username)
        except CredentialError as exc:
            return False, f"Could not read SFTP password: {exc}"

        if not effective_password:
            self._sftp_ready = False
            self._sftp_status_message = "Missing SFTP password."
            self._refresh_upload_ui_state()
            return True, self._sftp_status_message

        # No network here — reload_settings checks the connection in the background.
        self._sftp_recheck_pending = True
        self._sftp_ready = False
        self._sftp_status_message = self.SFTP_CHECK_PENDING_MESSAGE
        self._refresh_upload_ui_state()
        return True, "Credentials saved. The connection is checked in the background."

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

    def analyze_activity_log(self, activity_log_path: str) -> tuple[bool, str]:
        """Summarize an ASM Activity Log and compare active staff against current output."""
        generated_staff_ids: set[str] | None = None
        if self._last_result is not None:
            generated_staff_ids = {
                (row.get("person_id", "") or "").strip()
                for row in self._last_result.staff
                if isinstance(row, dict)
            }
            generated_staff_ids.discard("")

        try:
            summary = summarize_activity_log(
                activity_log_path,
                generated_staff_ids=generated_staff_ids,
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"Could not analyze activity log: {exc}"

        return True, render_activity_log_summary(summary)

    def get_diff_baseline_config(self) -> tuple[str, str]:
        mode = self._normalize_diff_baseline_mode(self._settings.get("diff_baseline_mode", "snapshot"))
        path = (self._settings.get("diff_baseline_path", "") or "").strip()

        # Migration bridge: prior setting stored only activity-log path for staff baseline.
        if mode == "snapshot" and not path:
            legacy_path = (self._settings.get("staff_diff_activity_log_path", "") or "").strip()
            if legacy_path:
                mode = "activity_log"
                path = legacy_path

        return mode, path

    def set_diff_baseline_from_activity_log(self, activity_log_path: str) -> tuple[bool, str]:
        path = (activity_log_path or "").strip()
        if not path:
            return False, "Missing activity log path."

        try:
            baseline = extract_baseline_from_activity_log(
                path,
                location_id=(self._settings.get("location_id", "") or "").strip(),
                known_staff_ids=self._known_staff_ids(),
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"Could not use activity log as diff baseline: {exc}"

        total_rows = (
            len(baseline.students)
            + len(baseline.staff)
            + len(baseline.courses)
            + len(baseline.classes)
            + len(baseline.rosters)
        )
        if total_rows == 0:
            return False, "Activity log contains no active entries to use as baseline."

        self._settings["diff_baseline_mode"] = "activity_log"
        self._settings["diff_baseline_path"] = path
        self._settings["staff_diff_activity_log_path"] = path
        SettingsStore.save(self._settings)
        return True, (
            f"Diff baseline set to activity log {Path(path).name} "
            f"(students={len(baseline.students)}, staff={len(baseline.staff)}, "
            f"courses={len(baseline.courses)}, classes={len(baseline.classes)}, "
            f"rosters={len(baseline.rosters)})."
        )

    def set_diff_baseline_from_csv(self, csv_source_path: str) -> tuple[bool, str]:
        path = (csv_source_path or "").strip()
        if not path:
            return False, "Missing CSV/ZIP baseline path."

        try:
            baseline = load_baseline_from_csv_source(path, config=self.build_config())
        except Exception as exc:  # noqa: BLE001
            return False, f"Could not use CSV/ZIP as diff baseline: {exc}"

        total_rows = (
            len(baseline.students)
            + len(baseline.staff)
            + len(baseline.courses)
            + len(baseline.classes)
            + len(baseline.rosters)
        )
        if total_rows == 0:
            return False, "Selected CSV/ZIP baseline contains no records."

        self._settings["diff_baseline_mode"] = "csv"
        self._settings["diff_baseline_path"] = path
        self._settings["staff_diff_activity_log_path"] = ""
        SettingsStore.save(self._settings)

        return True, (
            f"Diff baseline set to CSV/ZIP source {Path(path).name} "
            f"(students={len(baseline.students)}, staff={len(baseline.staff)}, "
            f"courses={len(baseline.courses)}, classes={len(baseline.classes)}, "
            f"rosters={len(baseline.rosters)})."
        )

    def set_diff_baseline_from_last_export(self) -> tuple[bool, str]:
        export_paths = [
            (path or "").strip()
            for path in self._settings.get("last_export_paths", [])
            if (path or "").strip()
        ]
        if not export_paths:
            return False, "No previous export paths are configured yet."

        existing_paths = [path for path in export_paths if Path(path).exists()]
        if not existing_paths:
            return False, "Configured export files were not found on disk."

        ok, message = self.set_diff_baseline_from_csv(existing_paths[0])
        if not ok:
            return False, message

        return True, f"Diff baseline set from last export: {message}"

    def clear_diff_baseline(self) -> tuple[bool, str]:
        self._settings["diff_baseline_mode"] = "snapshot"
        self._settings["diff_baseline_path"] = ""
        self._settings["staff_diff_activity_log_path"] = ""
        SettingsStore.save(self._settings)
        return True, "Diff baseline reset to snapshot."

    # Compatibility aliases for previous staff-only baseline controls.
    def get_staff_diff_activity_log_path(self) -> str:
        mode, path = self.get_diff_baseline_config()
        if mode == "activity_log":
            return path
        return ""

    def set_staff_diff_activity_log_path(self, activity_log_path: str) -> tuple[bool, str]:
        return self.set_diff_baseline_from_activity_log(activity_log_path)

    def clear_staff_diff_activity_log_path(self) -> tuple[bool, str]:
        return self.clear_diff_baseline()

    def _build_snapshot_for_diff(self, snapshot: GeneratorResult | None) -> GeneratorResult | None:
        """Resolve effective diff baseline from snapshot/activity-log/CSV settings."""
        mode, path = self.get_diff_baseline_config()
        if mode == "snapshot" or not path:
            return snapshot

        try:
            if mode == "activity_log":
                return extract_baseline_from_activity_log(
                    path,
                    location_id=(self._settings.get("location_id", "") or "").strip(),
                    known_staff_ids=self._known_staff_ids(snapshot),
                )
            if mode == "csv":
                return load_baseline_from_csv_source(path, config=self.build_config())
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to load configured diff baseline (mode=%s, path=%s)",
                mode,
                path,
                exc_info=exc,
            )

        return snapshot

    def _known_staff_ids(self, snapshot: GeneratorResult | None = None) -> set[str]:
        """Staff ids from the last snapshot and the current run.

        An activity log has no role column, so on its own it cannot tell a
        uuid-keyed teacher from a student.
        """
        if snapshot is None:
            try:
                snapshot = load_snapshot()
            except Exception:  # noqa: BLE001 - without the hint the log is only less precise
                snapshot = None
        known: set[str] = set()
        for source in (snapshot, self._last_result):
            for row in getattr(source, "staff", None) or []:
                pid = (row.get("person_id", "") or "").strip()
                if pid:
                    known.add(pid)
        return known

    def _has_sftp_credentials(self) -> bool:
        username = (self._settings.get("sftp_username", "") or "").strip()
        if not username or not is_keyring_available():
            return False
        try:
            return bool(get_password(username))
        except CredentialError:
            return False

    def _resolve_sftp_credentials(self) -> tuple[str, str, str]:
        """Return ``(username, password, error)`` without touching the network.

        ``error`` is empty when both username and password are available;
        otherwise it carries the status message explaining what is missing.
        """
        username = (self._settings.get("sftp_username", "") or "").strip()
        if not username:
            return "", "", "Missing SFTP username."

        if not is_keyring_available():
            return username, "", "Secure keyring backend is unavailable."

        try:
            password = get_password(username)
        except CredentialError as exc:
            return username, "", f"Credential error: {exc}"

        if not password:
            return username, "", "Missing SFTP password."

        return username, password, ""

    def _refresh_sftp_status(self, check_connection: bool) -> None:
        """Recompute upload readiness.

        With ``check_connection=True`` this blocks for up to
        ``sftp_client._CONNECT_TIMEOUT`` seconds, so only call it from an
        explicit user action (Save / Test Connection).  Startup uses
        :meth:`_start_sftp_status_check` instead.
        """
        # This result is authoritative — retire any probe still in flight.
        self._sftp_check_token += 1
        username, password, error = self._resolve_sftp_credentials()
        if error:
            self._sftp_ready = False
            self._sftp_status_message = error
            return

        if check_connection:
            check_result = check_sftp_connection(username, password)
            self._sftp_ready, self._sftp_status_message = self._normalize_sftp_check_result(check_result)
        else:
            self._sftp_ready = True
            self._sftp_status_message = "SFTP credentials available."

    def _start_sftp_status_check(self) -> bool:
        """Probe the SFTP server on a worker thread.  Never blocks the caller.

        The probe is a blocking TCP connect with a 15 s timeout; running it
        inline froze the window for the full timeout on networks that filter
        outbound port 22.  Returns True if a probe was dispatched, False if a
        credential prerequisite was missing (status is then already final).
        """
        # Any probe still in flight is superseded by this one.
        self._sftp_check_token += 1

        username, password, error = self._resolve_sftp_credentials()
        if error:
            self._sftp_ready = False
            self._sftp_status_message = error
            self._refresh_upload_ui_state()
            return False

        # Upload stays disabled while the probe is in flight — readiness is unknown.
        self._sftp_ready = False
        self._sftp_status_message = self.SFTP_CHECK_PENDING_MESSAGE
        self._refresh_upload_ui_state()

        worker = SftpStatusWorker(
            check_sftp_connection, username, password, self._sftp_check_token
        )
        worker.signals.finished.connect(self._on_sftp_check_finished)
        worker.start()
        return True

    def _on_sftp_check_finished(self, token: int, ready: bool, message: str) -> None:
        """Apply a probe result on the GUI thread; drop superseded probes."""
        if token != self._sftp_check_token:
            return
        self._sftp_ready = ready
        self._sftp_status_message = message
        self._refresh_upload_ui_state()

    def _refresh_upload_ui_state(self) -> None:
        if self._diff_page is not None:
            self._diff_page.set_upload_available(self._sftp_ready, self._sftp_status_message)
        if self._settings_page is not None:
            self._settings_page.set_sftp_status(self._sftp_ready, self._sftp_status_message)

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    def start_update_check(self) -> None:
        """Ask GitHub for a newer release without blocking. Offline just leaves a status."""
        self._update_check_token += 1
        if not update_check.parse_version(update_check.current_version()):
            # From source: nothing to compare, and no thread for tests to trip over.
            self._set_update_status(None, "Development build — updates are only checked in the installed app.")
            return
        self._set_update_status(None, "Checking for updates…")
        worker = UpdateCheckWorker(self._update_check_token)
        worker.signals.checked.connect(self._on_update_checked)
        worker.start()

    def get_update_status(self) -> tuple[str, bool]:
        return self._update_message, self._update_release is not None

    def _set_update_status(self, release, message: str) -> None:
        self._update_release = release
        self._update_message = message
        if self._settings_page is not None and hasattr(self._settings_page, "set_update_status"):
            self._settings_page.set_update_status(message, release is not None)

    def _on_update_checked(self, token: int, release, message: str) -> None:
        if token != self._update_check_token:
            return
        self._set_update_status(release, message)
        if release is None:
            return
        content = f"ASM Generator {release.tag} is available."
        if update_check.staging_dir(update_check.install_dir()).exists():
            content += " The last update could not replace the program folder — close any window showing it and try again."
        bar = InfoBar.info(
            title="Update available",
            content=content,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            duration=-1,
            position=InfoBarPosition.BOTTOM,
            parent=self._window,
        )
        button = PushButton("Update now")
        button.clicked.connect(bar.close)
        button.clicked.connect(self.install_update)
        bar.addWidget(button)

    def install_update(self) -> None:
        release = self._update_release
        if release is None or self._update_worker is not None:
            return
        problem = update_check.install_problem(release)
        if problem:
            MessageBox(
                "Automatic update not possible",
                f"{problem}\n\nDownload {release.tag} yourself from:\n{release.page}",
                self._window,
            ).exec()
            return
        confirm = MessageBox(
            "Install update?",
            f"Download ASM Generator {release.tag} ({release.size // 1_000_000} MB), then close "
            "and restart the app.\n\nAn unfinished review is lost. The current version is kept "
            "as a backup folder next to the program.",
            self._window,
        )
        if not confirm.exec():
            return

        progress = QProgressDialog("Downloading update…", "Cancel", 0, 100, self._window)
        progress.setWindowTitle("Updating ASM Generator")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        worker = UpdateInstallWorker(release, update_check.install_dir())
        worker.signals.progress.connect(progress.setValue)
        worker.signals.staged.connect(self._on_update_staged)
        worker.signals.failed.connect(self._on_update_failed)
        progress.canceled.connect(worker.cancel)
        self._update_progress = progress
        self._update_worker = worker
        worker.start()
        progress.show()

    def _close_update_progress(self) -> None:
        self._update_worker = None
        if self._update_progress is not None:
            self._update_progress.close()
            self._update_progress = None

    def _on_update_staged(self, staging: str) -> None:
        self._close_update_progress()
        update_check.launch_swap(
            update_check.install_dir(), Path(staging), update_check.current_version()
        )
        QApplication.quit()

    def _on_update_failed(self, message: str) -> None:
        self._close_update_progress()
        if message != "Update cancelled.":
            MessageBox("Update failed", message, self._window).exec()

    def build_config(self) -> GeneratorConfig:
        """Build GeneratorConfig from current settings, resolving empty paths to bundled defaults."""

        def _resolve(path_str: str, filename: str, fallback: str = "") -> str:
            if path_str:
                return path_str
            # Frozen (PyInstaller): sys._MEIPASS; dev: project root
            base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
            primary = base / filename
            # teacher_aliases.json names real staff, so it is gitignored and
            # absent from a clean clone or a fresh install. Fall back to the
            # tracked empty stub rather than failing to generate at all.
            if fallback and not primary.is_file():
                return str(base / fallback)
            return str(primary)

        return GeneratorConfig(
            location_id=self._settings.get("location_id", ""),
            email_domain=self._settings.get("email_domain", ""),
            aliases_path=_resolve(
                self._settings.get("teacher_aliases_path", ""),
                "teacher_aliases.json",
                fallback="teacher_aliases.empty.json",
            ),
            subjects_path=_resolve(
                self._settings.get("subject_map_path", ""), "subject_map.json"
            ),
            input_mode=self._settings.get("input_mode", "schuldock"),
            target_school_year=self._settings.get("target_school_year", ""),
            # "name" if absent — SettingsStore only hands out "interne_id" to a
            # genuinely fresh install, never to one with accounts already keyed.
            staff_id_source=self._settings.get("staff_id_source", "name"),
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
            # Keeps staff on the ASM account they already have when Schuldock
            # renames them; empty map = ids derived exactly as before.
            person_pins=person_pins.load(),
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

        self._warn_if_staff_ids_were_rekeyed(result, snapshot)

        # Most warnings are routine ("no instructor for offer …"). Only those that
        # change who ends up in which class are put in front of the user.
        review = [w[len("REVIEW: "):] for w in (getattr(result, "warnings", None) or []) if w.startswith("REVIEW: ")]
        if review:
            shown = "\n\n".join(f"• {w}" for w in review[:_MAX_REVIEW_NOTES])
            if len(review) > _MAX_REVIEW_NOTES:
                shown += f"\n\n…and {len(review) - _MAX_REVIEW_NOTES} more."
            MessageBox("Check before exporting", shown, self._window).exec()

        diff_snapshot = self._build_snapshot_for_diff(snapshot)
        diff_result = compute_diff(result, diff_snapshot)
        self._diff_page.load_diff(diff_result, self._build_asm_state(snapshot))
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
        self._remember_pins(result)
        if not self._save_snapshot_or_warn(result, "export", f"The ZIP was written to:\n{path}"):
            return

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

            backup_path = None
            try:
                backup_path = create_backup(zip_path)
            except Exception as exc:  # noqa: BLE001
                box = MessageBox(
                    "Backup Failed",
                    (
                        "Could not create local backup before upload.\n\n"
                        f"{exc}\n\n"
                        "Proceed without backup?"
                    ),
                    self._window,
                )
                if hasattr(box, "yesButton"):
                    box.yesButton.setText("Proceed without backup")
                if hasattr(box, "cancelButton"):
                    box.cancelButton.setText("Cancel upload")
                if not box.exec():
                    return

            attempt = 1
            while True:
                try:
                    remote_name = upload_file(zip_path, username=username, password=password)
                    break
                except Exception as exc:  # noqa: BLE001
                    classification = self._classify_upload_exception(exc)
                    logger.warning(
                        "SFTP upload attempt %s failed (category=%s)",
                        attempt,
                        classification["category"],
                        exc_info=exc,
                    )
                    box = MessageBox(
                        str(classification["title"]),
                        str(classification["body"]),
                        self._window,
                    )
                    if hasattr(box, "yesButton"):
                        box.yesButton.setText("Retry")
                    if hasattr(box, "cancelButton"):
                        box.cancelButton.setText("Cancel")
                    if not bool(classification["retryable"]) or not box.exec():
                        return
                    attempt += 1

        # ASM now holds these ids whatever happens to the local files.
        self._remember_pins(result)
        kept = f"The uploaded ZIP is kept at:\n{backup_path}" if backup_path else "No local backup of the ZIP exists."
        # ponytail: returning before reset() on purpose — the review stays
        # loaded, so nothing is lost; never move the reset above this check.
        if not self._save_snapshot_or_warn(
            result,
            "upload",
            f"The upload to Apple succeeded ({remote_name}).\n{kept}\n\n"
            "Do not upload again before checking the result in ASM.",
        ):
            return

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
        result = GeneratorResult(
            students=approved["students"],
            staff=approved["staff"],
            courses=approved["courses"],
            classes=approved["classes"],
            rosters=approved["rosters"],
            warnings=self._last_result.warnings if self._last_result else [],
            # Not narrowed to the approved rows — _remember_pins does that by
            # intersecting with the person_ids actually in this result.
            staff_uids=getattr(self._last_result, "staff_uids", {}) or {},
        )

        # self._last_result still holds the held-back rows, so it is what turns
        # their ids back into names for the report.
        notes = _prune_dangling_references(result, self._last_result)
        if notes:
            MessageBox(
                "Held-back records affect other rows",
                "Rows you left unticked are referenced elsewhere. ASM rejects a "
                "file that points at a person or class it was never given, so "
                "these were dropped too:\n\n• " + "\n\n• ".join(notes),
                self._window,
            ).exec()
        return result

    def _warn_if_staff_ids_were_rekeyed(
        self, result: GeneratorResult, snapshot: GeneratorResult | None
    ) -> None:
        """Catch the whole staff being re-keyed at once, before it is reviewed.

        Switching staff_id_source on a school that already has ASM staff accounts
        deactivates every one of them and creates them again under new ids. It
        arrives in the review looking like an ordinary pile of ADDED and DELETED
        rows, which is exactly how it would get waved through.
        """
        if snapshot is None or not snapshot.staff:
            return
        was = _staff_key_scheme(snapshot.staff)
        now = _staff_key_scheme(result.staff)
        if was == "unknown" or now == "unknown" or was == now:
            return

        stranded = {(r.get("person_id") or "") for r in snapshot.staff}
        stranded -= {(r.get("person_id") or "") for r in result.staff}

        direction = "names to SIS ids" if now == "uuid" else "SIS ids to names"
        MessageBox(
            "Every staff person_id has changed",
            f"The staff id scheme moved from {direction}, so "
            f"{len(stranded):,} existing staff accounts would be deactivated "
            "and created again under new ids.\n\n"
            "ASM keys accounts on person_id, so this cannot be undone once "
            "uploaded — mail, data and sign-ins stay with the deactivated "
            "accounts.\n\n"
            "If this was not deliberate, close without exporting and set "
            "'Staff ID source' in Settings back to its previous value.",
            self._window,
        ).exec()

    def get_asm_state_log_path(self) -> str:
        return (self._settings.get("asm_state_log_path", "") or "").strip()

    def set_asm_state_log(self, path: str) -> tuple[bool, str]:
        """Adopt an ASM activity log as evidence of what ASM currently holds."""
        path = (path or "").strip()
        if not path:
            return False, "No activity log selected."
        try:
            state = load_person_state(path)
        except Exception as exc:  # noqa: BLE001
            return False, f"Could not read the activity log: {exc}"
        if not state:
            return False, "That log records no successful person operations."

        self._settings["asm_state_log_path"] = path
        SettingsStore.save(self._settings)
        live = sum(1 for active in state.values() if active)
        return True, (
            f"{len(state):,} people found — {live:,} active, {len(state) - live:,} "
            "deactivated.\n\nA log only names the people that changed in that sync, "
            "so anyone it does not mention still shows as '?'."
        )

    def _build_asm_state(self, snapshot: GeneratorResult | None) -> AsmState:
        """Assemble the best available evidence about what ASM holds.

        Never raises: a missing or unreadable log downgrades the answer to
        UNKNOWN, which the review already treats as 'do not assume safe'.
        """
        log_state: dict[str, bool] = {}
        path = (self._settings.get("asm_state_log_path", "") or "").strip()
        if path:
            try:
                log_state = load_person_state(path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not read ASM state log %s: %s", path, exc, exc_info=exc)

        # Only an uploaded snapshot is evidence: an exported ZIP may never have
        # been sent, and a snapshot from before an id-rule change describes a
        # file rather than ASM.
        confirmed = load_provenance().get("via") == "upload"
        ids = None
        if snapshot is not None:
            ids = {r.get("person_id") for r in (*snapshot.students, *snapshot.staff)}
        return AsmState(log_state, ids, snapshot_confirmed=confirmed)

    def _remember_pins(self, result: GeneratorResult) -> None:
        """Pin the staff ids this export just handed ASM. Never fails an export."""
        try:
            exported = {r.get("person_id", "") for r in result.staff}
            added = person_pins.remember(result.staff_uids, exported)
            if added:
                logger.info("pinned %d newly exported staff id(s)", len(added))
        except Exception as exc:  # noqa: BLE001 — the ZIP is already written
            logger.warning("Could not update person pins: %s", exc, exc_info=exc)

    def _save_snapshot_or_warn(self, result: GeneratorResult, via: str, done: str) -> bool:
        """Persist the snapshot; if that fails, say plainly what already happened."""
        try:
            save_snapshot(
                result, via=via, staff_id_source=self._settings.get("staff_id_source", "name")
            )
            return True
        except Exception as exc:  # noqa: BLE001 - disk full, locked file, missing folder
            logger.error("Could not save the snapshot after %s", via, exc_info=exc)
            MessageBox(
                "Local state not saved",
                f"{done}\n\nBut the snapshot could not be saved:\n{exc}\n\n"
                "The account ids were kept. The next review still compares against "
                "the previous snapshot, so these changes will show up again.",
                self._window,
            ).exec()
            return False

    def _write_zip_or_show_error(self, result: GeneratorResult, path: str, write_to_zip) -> bool:
        from asm_generator.writer import validate_result

        problems = validate_result(result)
        if problems:
            shown = "\n".join(f"• {p}" for p in problems[:10])
            if len(problems) > 10:
                shown += f"\n…and {len(problems) - 10} more."
            MessageBox(
                "Export blocked",
                "Apple School Manager would reject this file, so nothing was written:\n\n" + shown,
                self._window,
            ).exec()
            return False
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
