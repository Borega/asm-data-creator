"""Top-level generate() orchestrator — pure function, writes nothing to disk."""
from __future__ import annotations

from .config import GeneratorConfig, GeneratorResult
from .parsers import parse_export, parse_monolith, parse_students
from .transform import (
    build_class_records,
    build_course_records,
    build_student_records,
    build_student_records_monolith,
    build_teacher_records,
    drop_duplicate_classes,
    resolve_staff_identity,
)


def generate(
    config: GeneratorConfig,
    student_paths: list,
    export_paths: list,
    existing_staff: list | None = None,
    input_mode: str | None = None,
    monolith_paths: list | None = None,
    person_pins: dict | None = None,
) -> GeneratorResult:
    """Run the full ASM generation pipeline in memory.

    Returns a GeneratorResult with all five tables populated.
    Writes nothing to disk.

    Args:
        config: Runtime configuration (location_id, email_domain, aliases_path, subjects_path).
        student_paths: One or more paths to tab-separated student master CSV files.
        export_paths: One or more paths to semicolon-separated course-enrollment export files.
        existing_staff: Pre-loaded staff records (list of dicts from a previous staff.csv).
                        Pass [] or None if no existing staff data is available.
    """
    if existing_staff is None:
        existing_staff = []

    mode = (input_mode or config.input_mode or "schuldock").strip().lower()
    if mode == "monolith":
        mode = "schuldock"
    warnings: list[str] = []
    monolith_teacher_rows: list[dict] = []

    if mode == "schuldock":
        parsed_monolith = parse_monolith(monolith_paths or student_paths, config.target_school_year)
        parsed_students = parsed_monolith["students"]
        sections = parsed_monolith["sections"]
        monolith_teacher_rows = parsed_monolith.get("teachers", [])
        warnings.extend(parsed_monolith["warnings"])
        student_records = build_student_records_monolith(parsed_students, config)
    else:
        parsed_students = parse_students(student_paths)
        sections = parse_export(export_paths)
        student_records = build_student_records(parsed_students, config)

    teacher_records = build_teacher_records(
        sections,
        existing_staff,
        config,
        monolith_staff=monolith_teacher_rows,
        person_pins=person_pins,
    )
    courses_map = build_course_records(sections, config)
    classes, rosters, build_warnings = build_class_records(
        sections, courses_map, teacher_records, student_records, config
    )
    warnings.extend(build_warnings)

    courses, classes, rosters, dedupe_warnings = drop_duplicate_classes(
        list(courses_map.values()), classes, rosters
    )
    warnings.extend(dedupe_warnings)

    # Re-resolve each monolith row to the record it became. build_teacher_records
    # keys on (first, last), so this is the only place a Schuldock uuid and the
    # exported person_id meet; resolve_staff_identity is the same function that
    # built that key, so the two cannot drift apart.
    aliases = config.load_aliases()
    staff_uids: dict[str, str] = {}
    for row in monolith_teacher_rows:
        uid = (row.get("_uid", "") or "").strip()
        first, last, _, _ = resolve_staff_identity(row, aliases)
        record = teacher_records.get((first, last))
        if uid and record:
            staff_uids[uid] = record["person_id"]

    return GeneratorResult(
        students=student_records,
        staff=list(teacher_records.values()),
        staff_uids=staff_uids,
        courses=courses,
        classes=classes,
        rosters=rosters,
        warnings=warnings,
    )
