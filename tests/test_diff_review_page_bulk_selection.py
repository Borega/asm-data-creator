"""Regression tests for status-based bulk row selection in Diff Review."""

from __future__ import annotations

import os

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from diff_engine import DiffResult, DiffStatus, RowDiff, TableDiff
from gui.pages.diff_review_page import DiffReviewPage, _TabWidget

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


def test_keep_all_deletions_satisfies_the_gate_without_deleting_anything(qapp: QApplication):
    """Unticked already means keep; this records that it was a decision."""
    tab = _TabWidget(
        tab_key="students",
        key_columns=["person_id", "first_name", "last_name", "grade_level", "email_address"],
    )
    tab.populate(_mixed_students_table())
    assert tab.count_unreviewed_deletions() == 1, "gate blocks before any decision"

    assert tab.keep_all_deletions() == 1
    assert tab.count_unreviewed_deletions() == 0, "gate is satisfied"

    ids = {r["person_id"] for r in tab.get_approved_records()}
    assert "s-deleted-1" in ids, "the record must be retained, not deleted"


def test_keep_all_deletions_does_not_disturb_other_statuses(qapp: QApplication):
    tab = _TabWidget(
        tab_key="students",
        key_columns=["person_id", "first_name", "last_name", "grade_level", "email_address"],
    )
    tab.populate(_mixed_students_table())
    before = {
        m.row_diff.record_id: m.checkbox_item.checkState()
        for m in tab._row_metas
        if m.checkbox_item and m.row_diff.status != DiffStatus.DELETED
    }

    tab.keep_all_deletions()

    after = {
        m.row_diff.record_id: m.checkbox_item.checkState()
        for m in tab._row_metas
        if m.checkbox_item and m.row_diff.status != DiffStatus.DELETED
    }
    assert before == after and before, "ADDED/CHANGED decisions must be untouched"


def test_added_rows_default_to_creating_but_can_be_held_back(qapp: QApplication):
    """Schuldock keeps listing leavers; creating their account is work to undo."""
    tab = _TabWidget(
        tab_key="students",
        key_columns=["person_id", "first_name", "last_name", "grade_level", "email_address"],
    )
    tab.populate(_mixed_students_table())

    added = [m for m in tab._row_metas if m.row_diff.status == DiffStatus.ADDED]
    assert all(m.checkbox_item is not None for m in added), "ADDED needs a checkbox"
    assert all(m.checkbox_item.checkState() == Qt.CheckState.Checked for m in added)

    ids = {r["person_id"] for r in tab.get_approved_records()}
    assert {"s-added-1", "s-added-2"} <= ids

    added[0].checkbox_item.setCheckState(Qt.CheckState.Unchecked)
    ids = {r["person_id"] for r in tab.get_approved_records()}
    assert "s-added-1" not in ids, "an unticked ADDED row must not reach ASM"
    assert "s-added-2" in ids
    assert "s-unchanged-1" in ids, "holding one row back changes nothing else"


def test_holding_back_an_added_row_never_falls_back_to_a_snapshot(qapp: QApplication):
    """There is no previous version of a new person — the row just disappears."""
    tab = _TabWidget(
        tab_key="students",
        key_columns=["person_id", "first_name", "last_name", "grade_level", "email_address"],
    )
    tab.populate(TableDiff(rows=[_row("s-added-1", DiffStatus.ADDED)]))

    tab._row_metas[0].checkbox_item.setCheckState(Qt.CheckState.Unchecked)

    assert tab.get_approved_records() == []


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


# ---------------------------------------------------------------------------
# Acting on a selection, and filtering
# ---------------------------------------------------------------------------

_KEY_COLUMNS = ["person_id", "first_name", "last_name", "grade_level", "email_address"]


def _tab(table_diff: TableDiff) -> _TabWidget:
    tab = _TabWidget(tab_key="students", key_columns=_KEY_COLUMNS)
    tab.populate(table_diff)
    return tab


def test_approve_selected_confirms_deletions_and_clears_the_gate(qapp: QApplication):
    tab = _tab(_mixed_students_table())
    assert tab.count_unreviewed_deletions() == 1

    _status_button(tab, DiffStatus.DELETED).click()   # select the deleted rows
    tab._decide_selected(approve=True)

    deleted = [m for m in tab._row_metas if m.row_diff.status == DiffStatus.DELETED]
    assert all(m.checkbox_item.checkState() == Qt.CheckState.Checked for m in deleted)
    # blockSignals means _on_item_changed never fires — reviewed must be set directly.
    assert all(m.reviewed for m in deleted)
    assert tab.count_unreviewed_deletions() == 0
    approved_ids = {r["person_id"] for r in tab.get_approved_records()}
    assert "s-deleted-1" not in approved_ids


def test_keep_selected_marks_deletions_reviewed_without_deleting_them(qapp: QApplication):
    """Keeping a record is a decision; it used to require ticking and unticking."""
    tab = _tab(_mixed_students_table())

    _status_button(tab, DiffStatus.DELETED).click()
    tab._decide_selected(approve=False)

    deleted = [m for m in tab._row_metas if m.row_diff.status == DiffStatus.DELETED]
    assert all(m.checkbox_item.checkState() == Qt.CheckState.Unchecked for m in deleted)
    assert all(m.reviewed for m in deleted)
    assert tab.count_unreviewed_deletions() == 0
    approved_ids = {r["person_id"] for r in tab.get_approved_records()}
    assert "s-deleted-1" in approved_ids, "an un-approved deletion must stay in the export"


def test_decide_selected_ignores_rows_hidden_by_the_filter(qapp: QApplication):
    tab = _tab(
        TableDiff(rows=[_row("keep-me", DiffStatus.DELETED), _row("other-1", DiffStatus.DELETED)])
    )

    tab._on_filter_changed("keep-me")
    visible = [m for m in tab._row_metas if not tab._table.isRowHidden(m.table_row)]
    assert [m.row_diff.record_id for m in visible] == ["keep-me"]

    _status_button(tab, DiffStatus.DELETED).click()   # selects visible rows only
    tab._decide_selected(approve=True)

    by_id = {m.row_diff.record_id: m for m in tab._row_metas}
    assert by_id["keep-me"].reviewed
    assert not by_id["other-1"].reviewed, "a filtered-away row must not be decided"
    assert tab.count_unreviewed_deletions() == 1


def test_filter_and_unchanged_toggle_compose(qapp: QApplication):
    tab = _tab(_mixed_students_table())
    unchanged = _status_rows(tab, DiffStatus.UNCHANGED)

    tab._toggle_unchanged()   # show unchanged
    assert not any(tab._table.isRowHidden(r) for r in unchanged)

    tab._on_filter_changed("s-added")
    assert all(tab._table.isRowHidden(r) for r in unchanged), (
        "filter must still hide unchanged rows that do not match"
    )

    tab._on_filter_changed("")
    assert not any(tab._table.isRowHidden(r) for r in unchanged), (
        "clearing the filter must restore the unchanged-toggle state"
    )


def test_changing_the_filter_drops_a_stale_selection(qapp: QApplication):
    """Otherwise hidden rows stay selected and the select-all toggle inverts."""
    tab = _tab(
        TableDiff(rows=[_row("keep-me", DiffStatus.DELETED), _row("other-1", DiffStatus.DELETED)])
    )

    _status_button(tab, DiffStatus.DELETED).click()
    assert _selected_rows(tab) == _status_rows(tab, DiffStatus.DELETED)

    tab._on_filter_changed("keep-me")
    assert _selected_rows(tab) == set(), "narrowing the view must clear the selection"

    # …so the next select-all selects the filtered set instead of deselecting it.
    _status_button(tab, DiffStatus.DELETED).click()
    visible = {m.table_row for m in tab._row_metas if not tab._table.isRowHidden(m.table_row)}
    assert _selected_rows(tab) == visible


def test_export_gate_enables_after_approving_a_filtered_selection(qapp: QApplication):
    page = DiffReviewPage(controller=None)
    page.load_diff(
        DiffResult(students=TableDiff(rows=[_row("s-deleted-1", DiffStatus.DELETED)]))
    )
    assert not page._export_btn.isEnabled()
    assert "1 deletion" in page._gate_label.text()

    tab = page._tab_widgets[0]
    tab._on_filter_changed("s-deleted")
    _status_button(tab, DiffStatus.DELETED).click()
    tab._decide_selected(approve=True)

    assert page._export_btn.isEnabled()
    assert page._gate_label.text() == ""
