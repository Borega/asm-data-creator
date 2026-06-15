"""ASM activity log parsing and summary helpers.

The exported activity CSV contains multiple table sections with different headers
(persons, classes, locations, courses, rosters). This module parses sections
robustly and produces a focused staff success/failure readout.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from asm_generator.config import GeneratorResult

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_PERSON_HEADER = (
    "person_id",
    "last_name",
    "first_name",
    "person_number",
    "operation_status",
    "operation_substatus",
    "timestamp",
    "email",
)
_CLASS_HEADER = (
    "class_id",
    "course_name",
    "class_number",
    "operation_status",
    "operation_substatus",
    "timestamp",
)
_LOCATION_HEADER = (
    "location_id",
    "location_name",
    "operation_status",
    "operation_substatus",
    "timestamp",
)
_COURSE_HEADER = (
    "course_id",
    "course_number",
    "course_name",
    "location_id",
    "operation_status",
    "operation_substatus",
    "timestamp",
)
_ROSTER_HEADER = (
    "roster_id",
    "class_id",
    "student_id",
    "operation_status",
    "operation_substatus",
    "timestamp",
)

_SECTION_HEADER_MAP: dict[tuple[str, ...], str] = {
    _PERSON_HEADER: "person",
    _CLASS_HEADER: "class",
    _LOCATION_HEADER: "location",
    _COURSE_HEADER: "course",
    _ROSTER_HEADER: "roster",
}
_SECTION_NAMES = ("person", "class", "location", "course", "roster")


def _normalize_cells(row: list[str]) -> list[str]:
    return [cell.strip() for cell in row]


def _row_to_dict(headers: list[str], row: list[str]) -> dict[str, str]:
    cells = list(row)
    if len(cells) < len(headers):
        cells.extend([""] * (len(headers) - len(cells)))
    elif len(cells) > len(headers):
        cells = cells[: len(headers)]
    return dict(zip(headers, cells))


def parse_activity_log(path: str | Path) -> dict:
    """Parse an ASM activity log CSV into metadata + sectioned rows."""
    log_path = Path(path)
    if not log_path.is_file():
        raise FileNotFoundError(f"Activity log file not found: {log_path}")

    metadata: dict[str, str] = {}
    sections: dict[str, list[dict[str, str]]] = {name: [] for name in _SECTION_NAMES}

    current_section: str | None = None
    current_headers: list[str] = []

    with open(log_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        for raw_row in reader:
            row = _normalize_cells(raw_row)
            if not row or not any(row):
                continue

            header_key = tuple(row)
            if header_key in _SECTION_HEADER_MAP:
                current_section = _SECTION_HEADER_MAP[header_key]
                current_headers = list(row)
                continue

            if current_section is None:
                if len(row) >= 2:
                    metadata[row[0]] = row[1]
                continue

            sections[current_section].append(_row_to_dict(current_headers, row))

    return {
        "path": str(log_path),
        "metadata": metadata,
        "sections": sections,
    }


def _is_uuid_like(value: str) -> bool:
    return bool(_UUID_RE.match((value or "").strip()))


def _is_staff_person_row(row: dict[str, str]) -> bool:
    person_id = (row.get("person_id", "") or "").strip()
    if not person_id:
        return False
    if person_id.startswith("SAMPLE-"):
        return False
    return not _is_uuid_like(person_id)


def _latest_by_key(rows: list[dict[str, str]], key_name: str) -> dict[str, dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    for row in rows:
        key = (row.get(key_name, "") or "").strip()
        if not key:
            continue
        timestamp = row.get("timestamp", "") or ""
        if key not in latest or timestamp > (latest[key].get("timestamp", "") or ""):
            latest[key] = row
    return latest


def _latest_by_person_id(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return _latest_by_key(rows, "person_id")


def _is_success_created_or_updated(row: dict[str, str]) -> bool:
    status = (row.get("operation_status", "") or "").strip().upper()
    substatus = (row.get("operation_substatus", "") or "").strip().upper()
    return status == "SUCCESS" and substatus in {"ADDED", "CREATED", "UPDATED"}


def extract_baseline_from_activity_log(
    path: str | Path,
    *,
    location_id: str = "",
) -> GeneratorResult:
    """Build a GeneratorResult baseline from activity-log latest successful events.

    The baseline spans all diff categories (students/staff/courses/classes/rosters).
    Per entity key, only the latest event is considered.
    """
    parsed = parse_activity_log(path)
    sections: dict[str, list[dict[str, str]]] = parsed["sections"]

    person_rows = sections["person"]
    student_events = [
        row
        for row in person_rows
        if (row.get("person_id", "") or "").strip()
        and _is_uuid_like((row.get("person_id", "") or "").strip())
    ]
    staff_events = [row for row in person_rows if _is_staff_person_row(row)]

    latest_students = _latest_by_person_id(student_events)
    latest_staff = _latest_by_person_id(staff_events)

    students: list[dict[str, str]] = []
    for row in latest_students.values():
        if not _is_success_created_or_updated(row):
            continue
        person_id = (row.get("person_id", "") or "").strip()
        if not person_id:
            continue
        students.append(
            {
                "person_id": person_id,
                "person_number": person_id,
                "first_name": (row.get("first_name", "") or "").strip(),
                "middle_name": "",
                "last_name": (row.get("last_name", "") or "").strip(),
                "grade_level": "",
                "email_address": (row.get("email", "") or "").strip(),
                "sis_username": "",
                "password_policy": "",
                "location_id": location_id,
            }
        )

    staff: list[dict[str, str]] = []
    for row in latest_staff.values():
        if not _is_success_created_or_updated(row):
            continue
        person_id = (row.get("person_id", "") or "").strip()
        if not person_id:
            continue
        staff.append(
            {
                "person_id": person_id,
                "person_number": (row.get("person_number", "") or "").strip(),
                "first_name": (row.get("first_name", "") or "").strip(),
                "last_name": (row.get("last_name", "") or "").strip(),
                "email_address": (row.get("email", "") or "").strip(),
                "sis_username": "",
                "location_id": location_id,
            }
        )

    latest_courses = _latest_by_key(sections["course"], "course_id")
    courses: list[dict[str, str]] = []
    for row in latest_courses.values():
        if not _is_success_created_or_updated(row):
            continue
        course_id = (row.get("course_id", "") or "").strip()
        if not course_id:
            continue
        courses.append(
            {
                "course_id": course_id,
                "course_number": (row.get("course_number", "") or "").strip(),
                "course_name": (row.get("course_name", "") or "").strip(),
                "location_id": (row.get("location_id", "") or "").strip() or location_id,
            }
        )

    latest_classes = _latest_by_key(sections["class"], "class_id")
    classes: list[dict[str, str]] = []
    for row in latest_classes.values():
        if not _is_success_created_or_updated(row):
            continue
        class_id = (row.get("class_id", "") or "").strip()
        if not class_id:
            continue
        classes.append(
            {
                "class_id": class_id,
                "class_number": (row.get("class_number", "") or "").strip(),
                "course_id": "",
                "instructor_id": "",
                "instructor_id_2": "",
                "instructor_id_3": "",
                "location_id": location_id,
            }
        )

    latest_rosters: dict[str, dict[str, str]] = {}
    for row in sections["roster"]:
        class_id = (row.get("class_id", "") or "").strip()
        student_id = (row.get("student_id", "") or "").strip()
        if not class_id or not student_id:
            continue
        key = f"{class_id}:{student_id}"
        timestamp = row.get("timestamp", "") or ""
        if key not in latest_rosters or timestamp > (latest_rosters[key].get("timestamp", "") or ""):
            latest_rosters[key] = row

    rosters: list[dict[str, str]] = []
    for row in latest_rosters.values():
        if not _is_success_created_or_updated(row):
            continue
        class_id = (row.get("class_id", "") or "").strip()
        student_id = (row.get("student_id", "") or "").strip()
        if not class_id or not student_id:
            continue
        rosters.append(
            {
                "roster_id": (row.get("roster_id", "") or "").strip(),
                "class_id": class_id,
                "student_id": student_id,
            }
        )

    students.sort(key=lambda r: (r["person_id"], r.get("last_name", ""), r.get("first_name", "")))
    staff.sort(key=lambda r: (r["person_id"], r.get("last_name", ""), r.get("first_name", "")))
    courses.sort(key=lambda r: (r["course_id"], r.get("course_number", "")))
    classes.sort(key=lambda r: (r["class_id"], r.get("class_number", "")))
    rosters.sort(key=lambda r: (r["class_id"], r["student_id"]))

    return GeneratorResult(
        students=students,
        staff=staff,
        courses=courses,
        classes=classes,
        rosters=rosters,
        warnings=[],
    )


def extract_active_staff_from_activity_log(
    path: str | Path,
    *,
    location_id: str = "",
) -> list[dict[str, str]]:
    """Return active staff identities from latest successful activity-log person events."""
    return extract_baseline_from_activity_log(path, location_id=location_id).staff


def summarize_activity_log(
    path: str | Path,
    *,
    generated_staff_ids: set[str] | None = None,
) -> dict:
    """Build a focused staff success/failure summary from an activity log."""
    parsed = parse_activity_log(path)
    metadata: dict[str, str] = parsed["metadata"]
    person_rows: list[dict[str, str]] = parsed["sections"]["person"]

    staff_events = [row for row in person_rows if _is_staff_person_row(row)]
    student_events = [
        row
        for row in person_rows
        if (row.get("person_id", "") or "").strip()
        and _is_uuid_like((row.get("person_id", "") or "").strip())
    ]

    latest_staff_by_id = _latest_by_person_id(staff_events)
    latest_staff_rows = list(latest_staff_by_id.values())

    latest_staff_success = [
        row
        for row in latest_staff_rows
        if _is_success_created_or_updated(row)
    ]
    latest_staff_deactivated = [
        row
        for row in latest_staff_rows
        if (row.get("operation_substatus", "") or "").strip().upper() == "DEACTIVATED"
    ]
    latest_staff_issues = [
        row
        for row in latest_staff_rows
        if row not in latest_staff_success and row not in latest_staff_deactivated
    ]

    generated_ids: set[str] | None = None
    if generated_staff_ids is not None:
        generated_ids = {(pid or "").strip() for pid in generated_staff_ids if (pid or "").strip()}

    potential_missing_active_staff: list[dict[str, str]] = []
    if generated_ids is not None:
        for row in latest_staff_success:
            person_id = (row.get("person_id", "") or "").strip()
            if person_id and person_id not in generated_ids:
                potential_missing_active_staff.append(row)

    def _sort_key(row: dict[str, str]) -> tuple[str, str, str]:
        return (
            (row.get("last_name", "") or "").lower(),
            (row.get("first_name", "") or "").lower(),
            (row.get("person_id", "") or "").lower(),
        )

    latest_staff_success.sort(key=_sort_key)
    latest_staff_deactivated.sort(key=_sort_key)
    latest_staff_issues.sort(key=_sort_key)
    potential_missing_active_staff.sort(key=_sort_key)

    return {
        "path": parsed["path"],
        "activity_id": metadata.get("ACTIVITY_ID", ""),
        "started_at": metadata.get("STARTED AT", ""),
        "ended_at": metadata.get("ENDED AT", ""),
        "status": metadata.get("STATUS", ""),
        "sub_status": metadata.get("SUB_STATUS", ""),
        "person_event_count": len(person_rows),
        "student_event_count": len(student_events),
        "staff_event_count": len(staff_events),
        "latest_staff_identity_count": len(latest_staff_rows),
        "latest_staff_success": latest_staff_success,
        "latest_staff_deactivated": latest_staff_deactivated,
        "latest_staff_issues": latest_staff_issues,
        "potential_missing_active_staff": potential_missing_active_staff,
    }


def _format_person_row(row: dict[str, str]) -> str:
    person_id = (row.get("person_id", "") or "").strip()
    first = (row.get("first_name", "") or "").strip()
    last = (row.get("last_name", "") or "").strip()
    substatus = (row.get("operation_substatus", "") or "").strip()
    email = (row.get("email", "") or "").strip()

    name = " ".join(part for part in (first, last) if part).strip()
    if name:
        base = f"{person_id} ({name})"
    else:
        base = person_id

    if substatus and email:
        return f"{base} — {substatus} — {email}"
    if substatus:
        return f"{base} — {substatus}"
    if email:
        return f"{base} — {email}"
    return base


def render_activity_log_summary(summary: dict, *, max_rows: int = 20) -> str:
    """Render a plain-text report for MessageBox/terminal output."""
    lines = [
        f"Activity Log: {Path(summary.get('path', '')).name}",
        f"Activity ID: {summary.get('activity_id', '') or 'n/a'}",
        (
            f"Status: {summary.get('status', '') or 'n/a'}"
            f" / {summary.get('sub_status', '') or 'n/a'}"
        ),
        (
            f"Window: {summary.get('started_at', '') or 'n/a'}"
            f" -> {summary.get('ended_at', '') or 'n/a'}"
        ),
        "",
        (
            f"Person events: {summary.get('person_event_count', 0)} "
            f"(students={summary.get('student_event_count', 0)}, "
            f"staff={summary.get('staff_event_count', 0)})"
        ),
        f"Latest unique staff identities: {summary.get('latest_staff_identity_count', 0)}",
        (
            f"Latest staff outcomes: success={len(summary.get('latest_staff_success', []))}, "
            f"deactivated={len(summary.get('latest_staff_deactivated', []))}, "
            f"issues={len(summary.get('latest_staff_issues', []))}"
        ),
    ]

    potential_missing = summary.get("potential_missing_active_staff", []) or []
    if potential_missing:
        lines.append(
            f"Potential missing active staff vs current output: {len(potential_missing)}"
        )
        for row in potential_missing[:max_rows]:
            lines.append(f"  - {_format_person_row(row)}")
        if len(potential_missing) > max_rows:
            lines.append(f"  … and {len(potential_missing) - max_rows} more")
    else:
        lines.append("Potential missing active staff vs current output: 0")

    deactivated = summary.get("latest_staff_deactivated", []) or []
    if deactivated:
        lines.append("")
        lines.append(f"Latest deactivated staff ({len(deactivated)}):")
        for row in deactivated[:max_rows]:
            lines.append(f"  - {_format_person_row(row)}")
        if len(deactivated) > max_rows:
            lines.append(f"  … and {len(deactivated) - max_rows} more")

    issues = summary.get("latest_staff_issues", []) or []
    if issues:
        lines.append("")
        lines.append(f"Latest staff issues ({len(issues)}):")
        for row in issues[:max_rows]:
            lines.append(f"  - {_format_person_row(row)}")
        if len(issues) > max_rows:
            lines.append(f"  … and {len(issues) - max_rows} more")

    return "\n".join(lines)
