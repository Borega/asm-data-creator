"""Tests for activity log parsing and summary readout."""

from __future__ import annotations

from pathlib import Path

from activity_log import (
    extract_active_staff_from_activity_log,
    extract_baseline_from_activity_log,
    parse_activity_log,
    render_activity_log_summary,
    summarize_activity_log,
)


def _write_activity_log(tmp_path: Path) -> Path:
    content = """OPERATION,SYNC_SOURCE
ACTIVITY_ID,activity-123
STARTED AT,2026-04-08T13:53:18.388Z
ENDED AT,2026-04-08T13:57:16.881Z
STATUS,COMPLETED
SUB_STATUS,COMPLETED_WITH_ERROR

person_id,last_name,first_name,person_number,operation_status,operation_substatus,timestamp,email
11111111-1111-1111-1111-111111111111,Schueler,Max,11111111-1111-1111-1111-111111111111,SUCCESS,CREATED,2026-04-08T13:55:40.000Z,max.schueler@example.org
anna.beispiel,Beispiel,Anna,AB,SUCCESS,CREATED,2026-04-08T13:54:00.000Z,anna.beispiel@example.org
anna.beispiel,Beispiel,Anna,AB,SUCCESS,UPDATED,2026-04-08T13:56:00.000Z,anna.beispiel@example.org
rosamaria.muster,Muster,Rosa Maria,RM,SUCCESS,DEACTIVATED,2026-04-08T13:56:10.000Z,
tom.tester,Tester,Tom,TT,ISSUE,OPERATION_NOT_ALLOWED,2026-04-08T13:56:20.000Z,tom.tester@example.org

class_id,course_name,class_number,operation_status,operation_substatus,timestamp
cls-1,Mathematik 6a,6a Ma,SUCCESS,CREATED,2026-04-08T13:56:30.000Z
"""
    path = tmp_path / "activity.csv"
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_activity_log_sections_and_metadata(tmp_path: Path):
    path = _write_activity_log(tmp_path)

    parsed = parse_activity_log(path)

    assert parsed["metadata"]["ACTIVITY_ID"] == "activity-123"
    assert parsed["metadata"]["STATUS"] == "COMPLETED"
    assert len(parsed["sections"]["person"]) == 5
    assert len(parsed["sections"]["class"]) == 1
    assert parsed["sections"]["class"][0]["class_id"] == "cls-1"


def test_summarize_activity_log_staff_outcomes_and_missing_active_staff(tmp_path: Path):
    path = _write_activity_log(tmp_path)

    summary = summarize_activity_log(path, generated_staff_ids={"anna.beispiel"})

    assert summary["person_event_count"] == 5
    assert summary["student_event_count"] == 1
    assert summary["staff_event_count"] == 4
    assert summary["latest_staff_identity_count"] == 3

    assert len(summary["latest_staff_success"]) == 1
    assert summary["latest_staff_success"][0]["person_id"] == "anna.beispiel"

    assert len(summary["latest_staff_deactivated"]) == 1
    assert summary["latest_staff_deactivated"][0]["person_id"] == "rosamaria.muster"

    assert len(summary["latest_staff_issues"]) == 1
    assert summary["latest_staff_issues"][0]["person_id"] == "tom.tester"

    assert summary["potential_missing_active_staff"] == []

    summary_missing = summarize_activity_log(path, generated_staff_ids=set())
    assert len(summary_missing["potential_missing_active_staff"]) == 1
    assert summary_missing["potential_missing_active_staff"][0]["person_id"] == "anna.beispiel"


def test_render_activity_log_summary_contains_key_sections(tmp_path: Path):
    path = _write_activity_log(tmp_path)
    summary = summarize_activity_log(path, generated_staff_ids=set())

    report = render_activity_log_summary(summary)

    assert "Activity Log:" in report
    assert "Latest staff outcomes:" in report
    assert "Potential missing active staff vs current output" in report
    assert "Latest deactivated staff" in report
    assert "Latest staff issues" in report


def test_extract_active_staff_from_activity_log_uses_latest_success_rows(tmp_path: Path):
    path = _write_activity_log(tmp_path)

    rows = extract_active_staff_from_activity_log(path, location_id="loc-001")

    assert rows == [
        {
            "person_id": "anna.beispiel",
            "person_number": "AB",
            "first_name": "Anna",
            "last_name": "Beispiel",
            "email_address": "anna.beispiel@example.org",
            "sis_username": "",
            "location_id": "loc-001",
        }
    ]


def test_extract_baseline_from_activity_log_covers_all_categories(tmp_path: Path):
    content = """OPERATION,SYNC_SOURCE
ACTIVITY_ID,activity-xyz
STARTED AT,2026-04-08T13:53:18.388Z
ENDED AT,2026-04-08T13:57:16.881Z
STATUS,COMPLETED
SUB_STATUS,COMPLETED_WITH_ERROR

person_id,last_name,first_name,person_number,operation_status,operation_substatus,timestamp,email
11111111-1111-1111-1111-111111111111,Schueler,Max,11111111-1111-1111-1111-111111111111,SUCCESS,UPDATED,2026-04-08T13:55:40.000Z,max.schueler@example.org
teacher.one,One,Teacher,T1,SUCCESS,CREATED,2026-04-08T13:56:00.000Z,teacher.one@example.org

class_id,course_name,class_number,operation_status,operation_substatus,timestamp
cls-1,Mathematik 6a,6a Ma,SUCCESS,CREATED,2026-04-08T13:56:30.000Z

course_id,course_number,course_name,location_id,operation_status,operation_substatus,timestamp
crs-1,6a Ma,Mathematik 6a,loc-001,SUCCESS,UPDATED,2026-04-08T13:56:20.000Z

roster_id,class_id,student_id,operation_status,operation_substatus,timestamp
r-1,cls-1,11111111-1111-1111-1111-111111111111,SUCCESS,ADDED,2026-04-08T13:56:50.000Z
"""
    path = tmp_path / "activity-full.csv"
    path.write_text(content, encoding="utf-8")

    baseline = extract_baseline_from_activity_log(path, location_id="loc-001")

    assert len(baseline.students) == 1
    assert len(baseline.staff) == 1
    assert len(baseline.courses) == 1
    assert len(baseline.classes) == 1
    assert len(baseline.rosters) == 1


