"""A stale snapshot makes the review's own labels lie. Does the guard catch it?

Two failure modes, both reproduced here against the real evidence rules:
an ADDED row that already has a live ASM account (holding it back deactivates
that account), and a DELETED row ASM never had (keeping it creates a
duplicate — which has happened, five times in one upload).
"""

from __future__ import annotations

import os

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from asm_state import AsmState
from diff_engine import DiffStatus, RowDiff, TableDiff
from gui.pages.diff_review_page import _TabWidget

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_COLS = ["person_id", "first_name", "last_name", "email_address"]


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _rec(pid: str, first: str, last: str) -> dict:
    return {"person_id": pid, "first_name": first, "last_name": last,
            "email_address": f"{pid}@school.example"}


def _tab(rows: list[RowDiff], state: AsmState) -> _TabWidget:
    tab = _TabWidget(tab_key="staff", key_columns=_COLS)
    tab.populate(TableDiff(rows=rows), state)
    return tab


def _untick(tab: _TabWidget, record_id: str) -> None:
    meta = next(m for m in tab._row_metas if m.row_diff.record_id == record_id)
    meta.checkbox_item.setCheckState(Qt.CheckState.Unchecked)


def test_holding_back_a_teacher_who_is_live_in_asm_is_flagged(qapp):
    """A teacher shown as ADDED by a stale snapshot, live in ASM all along."""
    rows = [RowDiff(record_id="lena.kern", status=DiffStatus.ADDED,
                    current=_rec("lena.kern", "Lena", "Kern"), snapshot=None)]
    tab = _tab(rows, AsmState(log_state={"lena.kern": True}))

    assert tab.risky_decisions() == [], "ticked is the safe default, no warning"

    _untick(tab, "lena.kern")
    assert tab.risky_decisions() == [("deactivate", "Lena Kern (lena.kern)")]


def test_holding_back_a_genuinely_new_teacher_is_not_flagged(qapp):
    """The feature still has to work: a real leaver-on-file can be held back."""
    rows = [RowDiff(record_id="neu.kollege", status=DiffStatus.ADDED,
                    current=_rec("neu.kollege", "Neu", "Kollege"), snapshot=None)]
    tab = _tab(rows, AsmState(snapshot_ids={"someone.else"}, snapshot_confirmed=True))

    _untick(tab, "neu.kollege")
    assert tab.risky_decisions() == [], "ASM has no account to destroy"


def test_keeping_a_deletion_asm_never_had_is_flagged(qapp):
    """An id kept from a stale snapshot that ASM never had: a duplicate is born."""
    rows = [RowDiff(record_id="jo.brandt", status=DiffStatus.DELETED,
                    current=None, snapshot=_rec("jo.brandt", "Jo", "Brandt"))]
    tab = _tab(rows, AsmState(snapshot_ids={"jo-hinrich.brandt"}, snapshot_confirmed=True))

    # Unticked is the default for DELETED, and unticked means 'keep' — the exact
    # state 'Keep all deletions' produces in one click.
    assert tab.risky_decisions() == [("duplicate", "Jo Brandt (jo.brandt)")]

    tab.keep_all_deletions()
    assert tab.risky_decisions() == [("duplicate", "Jo Brandt (jo.brandt)")], \
        "the bulk button must not launder the same decision"


def test_keeping_a_deletion_for_a_live_account_is_not_flagged(qapp):
    rows = [RowDiff(record_id="anna.meier", status=DiffStatus.DELETED,
                    current=None, snapshot=_rec("anna.meier", "Anna", "Meier"))]
    tab = _tab(rows, AsmState(log_state={"anna.meier": True}))
    assert tab.risky_decisions() == [], "ASM has it; keeping really does keep it"


def test_without_evidence_every_held_back_row_is_flagged(qapp):
    """No evidence loaded: nothing can be called safe, so warn on everything."""
    rows = [
        RowDiff(record_id="a.one", status=DiffStatus.ADDED,
                current=_rec("a.one", "A", "One"), snapshot=None),
        RowDiff(record_id="d.two", status=DiffStatus.DELETED,
                current=None, snapshot=_rec("d.two", "D", "Two")),
    ]
    tab = _tab(rows, AsmState())
    _untick(tab, "a.one")

    kinds = {kind for kind, _ in tab.risky_decisions()}
    assert kinds == {"deactivate", "duplicate"}


def test_non_people_tabs_have_no_asm_column_and_never_flag(qapp):
    """A course has no account to deactivate; the column would be noise."""
    tab = _TabWidget(tab_key="courses", key_columns=["course_id", "course_name"])
    assert not tab.shows_asm_state
    assert "In ASM" not in tab._all_columns
    assert tab.risky_decisions() == []


def test_the_asm_column_shows_the_three_states(qapp):
    rows = [
        RowDiff(record_id="live.one", status=DiffStatus.ADDED,
                current=_rec("live.one", "L", "One"), snapshot=None),
        RowDiff(record_id="gone.two", status=DiffStatus.ADDED,
                current=_rec("gone.two", "G", "Two"), snapshot=None),
        RowDiff(record_id="unknown.three", status=DiffStatus.ADDED,
                current=_rec("unknown.three", "U", "Three"), snapshot=None),
    ]
    tab = _tab(rows, AsmState(log_state={"live.one": True, "gone.two": False}))

    col = tab._all_columns.index("In ASM")
    labels = [tab._table.item(m.table_row, col).text() for m in tab._row_metas]
    assert labels == ["Yes", "No", "?"]
