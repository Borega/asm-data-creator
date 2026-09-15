"""Regression tests for the findings of the September 2026 code review."""
from datetime import datetime

import pytest

import activity_log
import backup_store
import snapshot_store
from asm_generator.config import GeneratorConfig, GeneratorResult
from asm_generator.transform import build_class_records
from asm_generator.writer import validate_result


@pytest.fixture
def config(tmp_path):
    aliases = tmp_path / "aliases.json"
    aliases.write_text("[]", encoding="utf-8")
    subjects = tmp_path / "subjects.json"
    subjects.write_text("{}", encoding="utf-8")
    return GeneratorConfig(
        location_id="LOC001", email_domain="school.example",
        aliases_path=str(aliases), subjects_path=str(subjects),
    )


def _student(pid, last, first):
    return {"person_id": pid, "last_name": last, "first_name": first}


def _row(last, first, student_id=""):
    return {"nachname": last, "vorname": first, "klassenname": "5a",
            "angebotsname": "5a Ma", "student_id": student_id}


def _section(rows, teacher=("Lena", "Lehrer")):
    return {"teacher_abbr": "", "teacher_first": teacher[0], "teacher_last": teacher[1],
            "angebotsname": "5a Ma", "rows": rows}


def _build(sections, students, config, teachers=None):
    return build_class_records(sections, {"5a Ma": {"course_id": "c-5a-ma"}}, teachers or {}, students, config)


# --- students are enrolled by id, never by a shared name -------------------

def test_students_sharing_a_name_are_enrolled_by_id(config):
    twins = [_student("uid-1", "Schmidt", "Anna"), _student("uid-2", "Schmidt", "Anna")]
    _, rosters, warnings = _build([_section([_row("Schmidt", "Anna", "uid-2")])], twins, config)
    assert [r["student_id"] for r in rosters] == ["uid-2"]
    assert warnings == []


def test_a_name_matching_two_students_enrols_nobody_and_says_so(config):
    twins = [_student("uid-1", "Schmidt", "Anna"), _student("uid-2", "Schmidt", "Anna")]
    _, rosters, warnings = _build([_section([_row("Schmidt", "Anna")])], twins, config)
    assert rosters == []
    assert any(w.startswith("REVIEW:") and "2 students" in w for w in warnings)


def test_legacy_rows_without_id_still_match_a_unique_name(config):
    _, rosters, _ = _build([_section([_row("Schmidt", "Anna Lena")])], [_student("uid-1", "Schmidt", "Anna")], config)
    assert [r["student_id"] for r in rosters] == ["uid-1"]


# --- a fourth teacher is reported, not silently dropped --------------------

def test_a_fourth_teacher_is_reported(config):
    names = [("Ada", "Eins"), ("Ben", "Zwei"), ("Cem", "Drei"), ("Dora", "Vier")]
    teachers = {name: {"person_id": f"t{i}"} for i, name in enumerate(names)}
    classes, _, warnings = _build([_section([], teacher=n) for n in names], [], config, teachers)
    assert classes[0]["instructor_id_3"] == "t2"
    assert any(w.startswith("REVIEW:") and "t3" in w for w in warnings)


# --- the final rows are checked before a ZIP is written --------------------

def _result(**changes):
    rows = dict(
        students=[{"person_id": "s1"}],
        staff=[{"person_id": "t1"}],
        courses=[{"course_id": "c1"}],
        classes=[{"class_id": "k1", "course_id": "c1", "instructor_id": "t1",
                  "instructor_id_2": "", "instructor_id_3": ""}],
        rosters=[{"roster_id": "r1", "class_id": "k1", "student_id": "s1"}],
    )
    rows.update(changes)
    return GeneratorResult(**rows)


def test_a_consistent_result_passes():
    assert validate_result(_result()) == []


@pytest.mark.parametrize("changes, expected", [
    (dict(staff=[]), "instructor t1 is not in staff"),
    (dict(students=[{"person_id": "s1"}, {"person_id": "s1"}]), "duplicate person_id s1"),
    (dict(courses=[]), "unknown course"),
    (dict(rosters=[{"class_id": "k1", "student_id": "gone"}]), "student gone is not in students"),
    (dict(students=[{"person_id": ""}], rosters=[]), "without person_id"),
])
def test_validation_names_what_asm_would_reject(changes, expected):
    problems = validate_result(_result(**changes))
    assert any(expected in p for p in problems), problems


# --- uuid-keyed staff in an activity log ----------------------------------

_LOG = """OPERATION,SYNC_SOURCE
ACTIVITY_ID,activity-1
STATUS,COMPLETED

person_id,last_name,first_name,person_number,operation_status,operation_substatus,timestamp,email
11111111-1111-1111-1111-111111111111,Kern,Lena,,SUCCESS,UPDATED,2026-09-01T10:00:00.000Z,
22222222-2222-2222-2222-222222222222,Brandt,Jo,Br,SUCCESS,UPDATED,2026-09-01T10:00:01.000Z,
"""


def test_uuid_keyed_staff_are_not_counted_as_students(tmp_path):
    path = tmp_path / "activity.csv"
    path.write_text(_LOG, encoding="utf-8")
    teacher = "22222222-2222-2222-2222-222222222222"

    baseline = activity_log.extract_baseline_from_activity_log(path, known_staff_ids={teacher})
    assert [r["person_id"] for r in baseline.staff] == [teacher]
    assert [r["person_id"] for r in baseline.students] == ["11111111-1111-1111-1111-111111111111"]

    summary = activity_log.summarize_activity_log(path, generated_staff_ids={teacher})
    assert (summary["staff_event_count"], summary["student_event_count"]) == (1, 1)


# --- backups and snapshot provenance --------------------------------------

def test_two_backups_in_the_same_second_are_both_kept(tmp_path, monkeypatch):
    class _SameSecond(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 15, 12, 0, 0)

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(backup_store, "datetime", _SameSecond)
    source = tmp_path / "asm_export.zip"
    source.write_bytes(b"zip")

    first = backup_store.create_backup(source)
    second = backup_store.create_backup(source)

    assert (first.parent.name, second.parent.name) == ("20260915_120000", "20260915_120000_2")
    assert first.is_file() and second.is_file()


def test_snapshot_records_how_staff_ids_were_built(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot_store, "SNAPSHOT_DIR", tmp_path)
    monkeypatch.setattr(snapshot_store, "SNAPSHOT_PATH", tmp_path / "snapshot.json")

    snapshot_store.save_snapshot(GeneratorResult(), via="upload", staff_id_source="name")
    assert snapshot_store.load_provenance()["staff_id_source"] == "name"

    snapshot_store.save_snapshot(GeneratorResult(), via="export")
    assert "staff_id_source" not in snapshot_store.load_provenance()
