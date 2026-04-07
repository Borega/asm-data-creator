"""Background workers for ASM Generator GUI."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QRunnable, QObject, pyqtSignal

from asm_generator import generate, GeneratorConfig, GeneratorResult

if TYPE_CHECKING:
    pass


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
    ) -> None:
        super().__init__()
        self.signals = _WorkerSignals()
        self._config = config
        self._student_paths = student_paths
        self._teacher_paths = teacher_paths
        self._export_paths = export_paths

    def run(self) -> None:
        try:
            self.signals.progress.emit(0)

            # Load teacher CSV files as existing_staff dicts (carry forward emails)
            existing_staff: list[dict] = []
            for path in self._teacher_paths:
                p = Path(path)
                if p.is_file():
                    try:
                        with open(p, encoding="utf-8-sig", newline="") as f:
                            reader = csv.DictReader(f)
                            existing_staff.extend(list(reader))
                    except Exception:
                        pass  # non-critical; generate() tolerates empty existing_staff

            result: GeneratorResult = generate(
                self._config,
                self._student_paths,
                self._export_paths,
                existing_staff=existing_staff,
            )
            self.signals.progress.emit(100)
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(str(exc))
