import pytest
from asm_generator.config import GeneratorResult
from diff_engine import (
    compute_diff, DiffStatus, RowDiff, TableDiff, DiffResult
)


def _make_result(students=None, staff=None, courses=None, classes=None, rosters=None):
    """Helper: build a minimal GeneratorResult for testing."""
    return GeneratorResult(
        students=students or [],
        staff=staff or [],
        courses=courses or [],
        classes=classes or [],
        rosters=rosters or [],
        warnings=[],
    )


class TestNoSnapshot:
    def test_all_added_when_no_snapshot(self):
        current = _make_result(students=[
            {"person_id": "s1", "first_name": "Anna", "last_name": "Müller"},
            {"person_id": "s2", "first_name": "Ben",  "last_name": "Koch"},
        ])
        result = compute_diff(current, snapshot=None)
        assert isinstance(result, DiffResult)
        assert result.students.added == 2
        assert result.students.deleted == 0
        assert result.students.changed == 0
        assert result.students.unchanged == 0
        assert all(r.status == DiffStatus.ADDED for r in result.students.rows)

    def test_no_snapshot_no_deletions_across_all_tables(self):
        current = _make_result(
            students=[{"person_id": "s1", "first_name": "A", "last_name": "B"}],
            staff=[{"person_id": "t1", "first_name": "C", "last_name": "D"}],
            courses=[{"course_id": "c1", "course_name": "Math"}],
            classes=[{"class_id": "cl1", "course_id": "c1"}],
            rosters=[{"roster_id": "roster-cl1-s1", "class_id": "cl1", "student_id": "s1"}],
        )
        result = compute_diff(current, snapshot=None)
        for table in (result.students, result.staff, result.courses, result.classes, result.rosters):
            assert table.deleted == 0


class TestChangedDeleted:
    def test_changed_record_detected(self):
        snap = _make_result(students=[
            {"person_id": "s1", "first_name": "Anna", "last_name": "Müller"},
        ])
        curr = _make_result(students=[
            {"person_id": "s1", "first_name": "Anna", "last_name": "Schmidt"},  # name changed
        ])
        result = compute_diff(curr, snapshot=snap)
        assert result.students.changed == 1
        assert result.students.unchanged == 0
        row = result.students.rows[0]
        assert row.status == DiffStatus.CHANGED
        assert row.snapshot["last_name"] == "Müller"
        assert row.current["last_name"] == "Schmidt"

    def test_deleted_record_detected(self):
        snap = _make_result(students=[
            {"person_id": "s1", "first_name": "A", "last_name": "B"},
            {"person_id": "s2", "first_name": "C", "last_name": "D"},
        ])
        curr = _make_result(students=[
            {"person_id": "s1", "first_name": "A", "last_name": "B"},
        ])
        result = compute_diff(curr, snapshot=snap)
        assert result.students.deleted == 1
        del_rows = [r for r in result.students.rows if r.status == DiffStatus.DELETED]
        assert del_rows[0].record_id == "s2"
        assert del_rows[0].current is None

    def test_added_record_detected(self):
        snap = _make_result(students=[
            {"person_id": "s1", "first_name": "A", "last_name": "B"},
        ])
        curr = _make_result(students=[
            {"person_id": "s1", "first_name": "A", "last_name": "B"},
            {"person_id": "s2", "first_name": "C", "last_name": "D"},
        ])
        result = compute_diff(curr, snapshot=snap)
        assert result.students.added == 1
        assert result.students.unchanged == 1


class TestUnchanged:
    def test_identical_records_are_unchanged(self):
        records = [
            {"person_id": "s1", "first_name": "A", "last_name": "B"},
            {"person_id": "s2", "first_name": "C", "last_name": "D"},
        ]
        snap = _make_result(students=records)
        curr = _make_result(students=[dict(r) for r in records])
        result = compute_diff(curr, snapshot=snap)
        assert result.students.unchanged == 2
        assert result.students.added == 0
        assert result.students.changed == 0
        assert result.students.deleted == 0


class TestRosterCompositeKey:
    def test_roster_keyed_on_class_student_not_roster_id(self):
        """Roster with different roster_id counters but same class+student is UNCHANGED."""
        snap = _make_result(rosters=[
            {"roster_id": "roster-00001", "class_id": "cls1", "student_id": "s1"},
        ])
        curr = _make_result(rosters=[
            {"roster_id": "roster-00042", "class_id": "cls1", "student_id": "s1"},
        ])
        result = compute_diff(curr, snapshot=snap)
        # Same class+student = same roster; different roster_id counter is not a change
        assert result.rosters.unchanged == 1
        assert result.rosters.changed == 0

    def test_roster_composite_key_format(self):
        """Record IDs in RowDiff use the composite key format."""
        curr = _make_result(rosters=[
            {"roster_id": "roster-00001", "class_id": "cls1", "student_id": "s1"},
        ])
        result = compute_diff(curr, snapshot=None)
        assert result.rosters.rows[0].record_id == "cls1:s1"


class TestTableDiffCounts:
    def test_total_count_consistency(self):
        snap = _make_result(students=[
            {"person_id": "s1", "first_name": "A", "last_name": "B"},
            {"person_id": "s2", "first_name": "C", "last_name": "D"},
        ])
        curr = _make_result(students=[
            {"person_id": "s1", "first_name": "A", "last_name": "Changed"},
            {"person_id": "s3", "first_name": "E", "last_name": "F"},
        ])
        td = compute_diff(curr, snapshot=snap).students
        total = td.added + td.changed + td.deleted + td.unchanged
        # s1 changed, s2 deleted, s3 added → 3 rows total
        assert total == len(td.rows)
        assert td.changed == 1
        assert td.deleted == 1
        assert td.added == 1
