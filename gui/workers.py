"""Background workers for ASM Generator GUI."""
from __future__ import annotations

import csv
import io
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

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
    ) -> None:
        super().__init__()
        self.signals = _WorkerSignals()
        self._config = config
        self._student_paths = student_paths
        self._teacher_paths = teacher_paths
        self._export_paths = export_paths
        self._input_mode = input_mode
        self._monolith_paths = monolith_paths or []

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
            )
            self.signals.progress.emit(100)
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(str(exc))
