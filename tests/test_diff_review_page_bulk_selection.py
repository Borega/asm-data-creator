"""Regression tests for status-based bulk row selection in Diff Review."""

from __future__ import annotations

import os

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from diff_engine import DiffStatus, RowDiff, TableDiff
from gui.pages.diff_review_page import _TabWidget

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Provide a headless QApplication for widget tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _student_record(record_id: str, *, first_name: str = "Ada", last_name: str = "Lovelace") -> dict:
    return {
        "person_id": record_id,
        "first_name": first_name,
        "last_name": last_name,
        "grade_level": "10",
        "email_address": f"{record_id}@example.org",
    }


def _row(record_id: str, status: DiffStatus) -> RowDiff:
    if status == DiffStatus.ADDED:
        return RowDiff(record_id=record_id, status=status, current=_student_record(record_id), snapshot=None)
    if status == DiffStatus.CHANGED:
        return RowDiff(
            record_id=record_id,
            status=status,
            current=_student_record(record_id, last_name="Changed"),
            snapshot=_student_record(record_id, last_name="Original"),
        )
    if status == DiffStatus.DELETED:
        return RowDiff(record_id=record_id, status=status, current=None, snapshot=_student_record(record_id))
    return RowDiff(
        record_id=record_id,
        status=status,
        current=_student_record(record_id),
        snapshot=_student_record(record_id),
    )


def _mixed_students_table() -> TableDiff:
    return TableDiff(
        rows=[
            _row("s-added-1", DiffStatus.ADDED),
            _row("s-changed-1", DiffStatus.CHANGED),
            _row("s-deleted-1", DiffStatus.DELETED),
            _row("s-unchanged-1", DiffStatus.UNCHANGED),
            _row("s-added-2", DiffStatus.ADDED),
        ]
    )


def _selected_rows(tab: _TabWidget) -> set[int]:
    model = tab._table.selectionModel()
    assert model is not None, "QTableWidget selection model must exist"
    return {idx.row() for idx in model.selectedRows()}


def _status_rows(tab: _TabWidget, status: DiffStatus) -> set[int]:
    return {meta.table_row for meta in tab._row_metas if meta.row_diff.status == status}


def _status_button(tab: _TabWidget, status: DiffStatus):
    attr_map = {
        DiffStatus.ADDED: "_select_all_added_btn",
        DiffStatus.CHANGED: "_select_all_changed_btn",
        DiffStatus.DELETED: "_select_all_deleted_btn",
    }
    attr = attr_map[status]
    assert hasattr(tab, attr), f"Missing bulk-selection button: {attr}"
    return getattr(tab, attr)


@pytest.mark.parametrize("status", [DiffStatus.ADDED, DiffStatus.CHANGED, DiffStatus.DELETED])
def test_status_bulk_selection_button_is_visible_when_status_exists(qapp: QApplication, status: DiffStatus):
    tab = _TabWidget(
        tab_key="students",
        key_columns=["person_id", "first_name", "last_name", "grade_level", "email_address"],
    )
    tab.populate(_mixed_students_table())

    btn = _status_button(tab, status)
    assert not btn.isHidden(), f"Expected visible button for status: {status.value}"


@pytest.mark.parametrize("status", [DiffStatus.ADDED, DiffStatus.CHANGED, DiffStatus.DELETED])
def test_status_button_click_toggles_select_all_then_deselect_all(qapp: QApplication, status: DiffStatus):
    tab = _TabWidget(
        tab_key="students",
        key_columns=["person_id", "first_name", "last_name", "grade_level", "email_address"],
    )
    tab.populate(_mixed_students_table())

    button = _status_button(tab, status)
    target_rows = _status_rows(tab, status)
    assert target_rows, f"fixture must include {status.value} rows"

    assert _selected_rows(tab) == set()

    button.click()
    assert _selected_rows(tab) == target_rows, (
        f"first click must select all {status.value} rows"
    )

    button.click()
    assert _selected_rows(tab) == set(), (
        f"second click must deselect all {status.value} rows"
    )


@pytest.mark.parametrize("missing_status", [DiffStatus.ADDED, DiffStatus.CHANGED, DiffStatus.DELETED])
def test_clicking_button_for_absent_status_is_noop(qapp: QApplication, missing_status: DiffStatus):
    statuses = [DiffStatus.ADDED, DiffStatus.CHANGED, DiffStatus.DELETED]
    rows = [_row(f"present-{s.value}", s) for s in statuses if s != missing_status]
    rows.append(_row("present-unchanged", DiffStatus.UNCHANGED))
    tab = _TabWidget(
        tab_key="students",
        key_columns=["person_id", "first_name", "last_name", "grade_level", "email_address"],
    )
    tab.populate(TableDiff(rows=rows))

    button = _status_button(tab, missing_status)
    before = _selected_rows(tab)
    button.click()
    assert _selected_rows(tab) == before, f"{missing_status.value} click should be a no-op when rows are absent"


@pytest.mark.parametrize("status", [DiffStatus.ADDED, DiffStatus.CHANGED, DiffStatus.DELETED])
def test_bulk_selection_does_not_change_export_semantics_or_deletion_gate(qapp: QApplication, status: DiffStatus):
    tab = _TabWidget(
        tab_key="students",
        key_columns=["person_id", "first_name", "last_name", "grade_level", "email_address"],
    )
    tab.populate(_mixed_students_table())

    changed_checkbox_before = {
        m.table_row: m.checkbox_item.checkState()
        for m in tab._row_metas
        if m.row_diff.status == DiffStatus.CHANGED and m.checkbox_item is not None
    }
    deleted_checkbox_before = {
        m.table_row: m.checkbox_item.checkState()
        for m in tab._row_metas
        if m.row_diff.status == DiffStatus.DELETED and m.checkbox_item is not None
    }
    deleted_reviewed_before = {
        m.table_row: m.reviewed
        for m in tab._row_metas
        if m.row_diff.status == DiffStatus.DELETED
    }
    unreviewed_before = tab.count_unreviewed_deletions()
    approved_before = tab.get_approved_records()

    button = _status_button(tab, status)
    button.click()

    changed_checkbox_after = {
        m.table_row: m.checkbox_item.checkState()
        for m in tab._row_metas
        if m.row_diff.status == DiffStatus.CHANGED and m.checkbox_item is not None
    }
    deleted_checkbox_after = {
        m.table_row: m.checkbox_item.checkState()
        for m in tab._row_metas
        if m.row_diff.status == DiffStatus.DELETED and m.checkbox_item is not None
    }
    deleted_reviewed_after = {
        m.table_row: m.reviewed
        for m in tab._row_metas
        if m.row_diff.status == DiffStatus.DELETED
    }

    assert changed_checkbox_after == changed_checkbox_before
    assert deleted_checkbox_after == deleted_checkbox_before
    assert deleted_reviewed_after == deleted_reviewed_before
    assert tab.count_unreviewed_deletions() == unreviewed_before
    assert tab.get_approved_records() == approved_before


def test_boundary_hidden_unchanged_rows_are_not_selected_by_status_buttons(qapp: QApplication):
    tab = _TabWidget(
        tab_key="students",
        key_columns=["person_id", "first_name", "last_name", "grade_level", "email_address"],
    )
    tab.populate(_mixed_students_table())

    unchanged_rows = _status_rows(tab, DiffStatus.UNCHANGED)
    assert unchanged_rows, "fixture must include unchanged rows"
    for row_idx in unchanged_rows:
        assert tab._table.isRowHidden(row_idx), "unchanged rows should start hidden"

    for status in (DiffStatus.ADDED, DiffStatus.CHANGED, DiffStatus.DELETED):
        _status_button(tab, status).click()

    selected = _selected_rows(tab)
    assert unchanged_rows.isdisjoint(selected), "hidden unchanged rows must never be selected by status actions"


@pytest.mark.parametrize("status", [DiffStatus.ADDED, DiffStatus.CHANGED, DiffStatus.DELETED])
def test_status_toggle_is_deterministic_over_many_rows(qapp: QApplication, status: DiffStatus):
    rows: list[RowDiff] = []
    for i in range(60):
        rows.extend(
            [
                _row(f"a-{i}", DiffStatus.ADDED),
                _row(f"c-{i}", DiffStatus.CHANGED),
                _row(f"d-{i}", DiffStatus.DELETED),
                _row(f"u-{i}", DiffStatus.UNCHANGED),
            ]
        )

    tab = _TabWidget(
        tab_key="students",
        key_columns=["person_id", "first_name", "last_name", "grade_level", "email_address"],
    )
    tab.populate(TableDiff(rows=rows))

    target_rows = _status_rows(tab, status)
    button = _status_button(tab, status)

    button.click()
    assert _selected_rows(tab) == target_rows

    button.click()
    assert _selected_rows(tab) == set()

    # Ensure checkbox/review gate invariants still hold under larger table size.
    assert tab.count_unreviewed_deletions() == 60
    changed_states = [
        m.checkbox_item.checkState()
        for m in tab._row_metas
        if m.row_diff.status == DiffStatus.CHANGED and m.checkbox_item is not None
    ]
    deleted_states = [
        m.checkbox_item.checkState()
        for m in tab._row_metas
        if m.row_diff.status == DiffStatus.DELETED and m.checkbox_item is not None
    ]
    assert all(state == Qt.CheckState.Checked for state in changed_states)
    assert all(state == Qt.CheckState.Unchecked for state in deleted_states)
