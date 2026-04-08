"""Top-level generate() orchestrator — pure function, writes nothing to disk."""
from __future__ import annotations
from pathlib import Path
from .config import GeneratorConfig, GeneratorResult
from .parsers import parse_students, parse_export, parse_monolith
from .transform import (
    build_student_records,
    build_student_records_monolith,
    build_teacher_records,
    build_course_records,
    build_class_records,
)


def generate(
    config: GeneratorConfig,
    student_paths: list,
    export_paths: list,
    existing_staff: list | None = None,
    input_mode: str | None = None,
    monolith_paths: list | None = None,
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

    if mode == "schuldock":
        parsed_monolith = parse_monolith(monolith_paths or student_paths, config.target_school_year)
        parsed_students = parsed_monolith["students"]
        sections = parsed_monolith["sections"]
        warnings.extend(parsed_monolith["warnings"])
        student_records = build_student_records_monolith(parsed_students, config)
    else:
        parsed_students = parse_students(student_paths)
        sections = parse_export(export_paths)
        student_records = build_student_records(parsed_students, config)

    teacher_records = build_teacher_records(sections, existing_staff, config)
    courses_map = build_course_records(sections, config)
    classes, rosters, build_warnings = build_class_records(
        sections, courses_map, teacher_records, student_records, config
    )
    warnings.extend(build_warnings)

    return GeneratorResult(
        students=student_records,
        staff=list(teacher_records.values()),
        courses=list(courses_map.values()),
        classes=classes,
        rosters=rosters,
        warnings=warnings,
    )
