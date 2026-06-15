"""Input page mode payload regressions."""

from __future__ import annotations

import os

import pytest
from PyQt6.QtWidgets import QApplication

from gui.pages.input_page import InputPage

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _ControllerStub:
    def get_settings(self) -> dict:
        return {"email_domain": "example.org"}


def test_schuldock_run_ignores_hidden_teacher_paths(qapp: QApplication):
    page = InputPage(controller=_ControllerStub())
    page.show()
    qapp.processEvents()

    page._input_mode = "schuldock"
    page._teacher_paths = ["old_teacher_snapshot.csv"]
    page._monolith_paths = ["Benutzer-Daten.csv"]

    captured: list[tuple[list[str], list[str], list[str], str, list[str]]] = []
    page.run_requested.connect(lambda students, teachers, exports, mode, monolith: captured.append((students, teachers, exports, mode, monolith)))

    page._on_run_clicked()

    assert len(captured) == 1
    _students, teachers, _exports, mode, monolith = captured[0]
    assert mode == "schuldock"
    assert teachers == []
    assert monolith == ["Benutzer-Daten.csv"]


def test_legacy_run_keeps_teacher_paths(qapp: QApplication):
    page = InputPage(controller=_ControllerStub())
    page.show()
    qapp.processEvents()

    page._input_mode = "legacy"
    page._teacher_paths = ["Teacher_20260402_1332.csv"]
    page._student_paths = ["Student_20260402_1042.csv"]
    page._export_paths = ["export_angebotSchueler_2026.04.02.13-40.csv"]

    captured: list[tuple[list[str], list[str], list[str], str, list[str]]] = []
    page.run_requested.connect(lambda students, teachers, exports, mode, monolith: captured.append((students, teachers, exports, mode, monolith)))

    page._on_run_clicked()

    assert len(captured) == 1
    students, teachers, exports, mode, _monolith = captured[0]
    assert mode == "legacy"
    assert students == ["Student_20260402_1042.csv"]
    assert teachers == ["Teacher_20260402_1332.csv"]
    assert exports == ["export_angebotSchueler_2026.04.02.13-40.csv"]
