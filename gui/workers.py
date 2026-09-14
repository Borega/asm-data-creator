"""Background workers for ASM Generator GUI."""
from __future__ import annotations

import csv
import io
import logging
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

import update_check
from asm_generator import GeneratorConfig, GeneratorResult, generate

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


class _WorkerSignals(QObject):
    finished = pyqtSignal(object)   # GeneratorResult
    error = pyqtSignal(str)
    progress = pyqtSignal(int)      # 0-100; emitted at start (0) and end (100)


class GeneratorWorker(QRunnable):
    """Runs asm_generator.generate() on a thread pool thread.

    Dispatch with: QThreadPool.globalInstance().start(worker)

    teacher_paths are loaded here as existing_staff records (DictReader of
    the previous staff.csv export) matching what generate() expects.
    """

    def __init__(
        self,
        config: GeneratorConfig,
        student_paths: list[str],
        teacher_paths: list[str],
        export_paths: list[str],
        input_mode: str = "legacy",
        monolith_paths: list[str] | None = None,
        person_pins: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.signals = _WorkerSignals()
        self._config = config
        self._student_paths = student_paths
        self._teacher_paths = teacher_paths
        self._export_paths = export_paths
        self._input_mode = input_mode
        self._monolith_paths = monolith_paths or []
        self._person_pins = person_pins or {}

    @staticmethod
    def _normalise_staff_rows(rows: list[dict]) -> list[dict]:
        """Remap raw Teacher master CSV rows to the existing_staff schema.

        Accepts two layouts:
        - staff.csv output  : has ``first_name`` / ``last_name`` columns — pass through unchanged.
        - Teacher master CSV: has ``foreName`` / ``longName`` columns — remap to staff schema.
        Rows that have neither format are silently dropped (non-critical path).
        """
        if not rows:
            return rows
        first_row = rows[0]
        if "first_name" in first_row and "last_name" in first_row:
            return rows  # already in expected format
        if "foreName" in first_row or "longName" in first_row:
            result = []
            for row in rows:
                first = row.get("foreName", "").strip()
                last = row.get("longName", "").strip()
                if not first and not last:
                    continue
                result.append({
                    "first_name": first,
                    "last_name": last,
                    "person_id": "",  # will be generated fresh
                    "person_number": row.get("name", row.get("pnr", "")),
                    "email_address": row.get("address.email", ""),
                    "sis_username": "",
                })
            return result
        return []  # unknown format — skip to avoid KeyError in build_teacher_records

    def run(self) -> None:
        try:
            self.signals.progress.emit(0)

            # Load teacher CSV files as existing_staff dicts (carry forward emails)
            existing_staff: list[dict] = []
            for path in self._teacher_paths:
                p = Path(path)
                if not p.is_file():
                    continue
                try:
                    with open(p, encoding="utf-8-sig", newline="") as f:
                        content = f.read()
                    # Auto-detect delimiter (tab for school exports, comma for staff.csv)
                    try:
                        dialect = csv.Sniffer().sniff(content[:2048], delimiters="\t,;")
                        delimiter = dialect.delimiter
                    except csv.Error:
                        delimiter = ","
                    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
                    rows = self._normalise_staff_rows(list(reader))
                    existing_staff.extend(rows)
                except Exception as exc:  # noqa: BLE001 — non-critical; tolerate empty
                    logger.warning(
                        "Could not load existing staff CSV %s: %s",
                        path,
                        exc,
                        exc_info=exc,
                    )

            result: GeneratorResult = generate(
                self._config,
                self._student_paths,
                self._export_paths,
                existing_staff=existing_staff,
                input_mode=self._input_mode,
                monolith_paths=self._monolith_paths,
                person_pins=self._person_pins,
            )
            self.signals.progress.emit(100)
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(str(exc))


class _SftpStatusSignals(QObject):
    finished = pyqtSignal(int, bool, str)  # token, ready, message


class SftpStatusWorker:
    """Probes the ASM SFTP server off the GUI thread.

    Dispatch with :meth:`start`.

    Deliberately a daemon ``threading.Thread`` rather than a QRunnable on the
    global QThreadPool: the probe is a blocking TCP connect with a 15 s timeout
    that cannot be cancelled, and QThreadPool waits for its runnables during
    teardown — pooling it would move the freeze from startup to shutdown.  A
    daemon thread lets the process exit immediately instead.

    ``signals`` is constructed on the calling (GUI) thread, so ``finished`` is
    queued back to that thread even though it is emitted from the worker.

    ``token`` is echoed back in ``finished`` so the controller can discard the
    result of a probe that a newer one has superseded.
    """

    def __init__(self, check_fn, username: str, password: str, token: int) -> None:
        self.signals = _SftpStatusSignals()
        self._check_fn = check_fn
        self._username = username
        self._password = password
        self._token = token

    def start(self) -> None:
        threading.Thread(
            target=self.run, name=f"sftp-status-probe-{self._token}", daemon=True
        ).start()

    def run(self) -> None:
        try:
            result = self._check_fn(self._username, self._password)
        except Exception as exc:  # noqa: BLE001 - a probe must never kill its thread
            logger.warning("SFTP status probe failed: %s", exc, exc_info=exc)
            self.signals.finished.emit(self._token, False, f"Connection error: {exc}")
            return

        if isinstance(result, tuple) and len(result) == 2:
            ready, message = result
            self.signals.finished.emit(
                self._token,
                ready is True,
                str(message or "Unexpected SFTP connection response."),
            )
        else:
            self.signals.finished.emit(self._token, False, "Unexpected SFTP connection response.")


class _UpdateSignals(QObject):
    checked = pyqtSignal(int, object, str)  # token, Release | None, message
    progress = pyqtSignal(int)              # 0-100 while downloading
    staged = pyqtSignal(str)                # unpacked new program folder
    failed = pyqtSignal(str)


class UpdateCheckWorker:
    """Asks GitHub for the latest release off the GUI thread.

    A daemon thread for the same reason as SftpStatusWorker: a slow network
    must delay neither the window appearing nor the app closing.
    """

    def __init__(self, token: int) -> None:
        self.signals = _UpdateSignals()
        self._token = token

    def start(self) -> None:
        threading.Thread(target=self.run, name="update-check", daemon=True).start()

    def run(self) -> None:
        release, message = update_check.check()
        self.signals.checked.emit(self._token, release, message)


class UpdateInstallWorker:
    """Downloads, verifies and unpacks a release beside the program folder."""

    def __init__(self, release, target: Path) -> None:
        self.signals = _UpdateSignals()
        self._release = release
        self._target = target
        self._cancel = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self.run, name="update-install", daemon=True).start()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            with tempfile.TemporaryDirectory() as folder:
                archive = update_check.download(
                    self._release, Path(folder), self.signals.progress.emit, self._cancel.is_set
                )
                staging = update_check.stage(archive, self._target)
        except Exception as exc:  # noqa: BLE001 - reported to the user, never kills the app
            logger.warning("Update failed: %s", exc, exc_info=exc)
            self.signals.failed.emit(str(exc))
            return
        self.signals.staged.emit(str(staging))
