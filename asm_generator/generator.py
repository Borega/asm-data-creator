"""Top-level generate() orchestrator — pure function, writes nothing to disk."""
from __future__ import annotations
from pathlib import Path
from .config import GeneratorConfig, GeneratorResult
from .parsers import parse_students, parse_export
from .transform import (
    build_student_records,
    build_teacher_records,
    build_course_records,
    build_class_records,
)


def generate(
    config: GeneratorConfig,
    student_paths: list,
    export_paths: list,
    existing_staff: list | None = None,
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

    parsed_students = parse_students(student_paths)
    sections = parse_export(export_paths)

    student_records = build_student_records(parsed_students, config)
    teacher_records = build_teacher_records(sections, existing_staff, config)
    courses_map = build_course_records(sections, config)
    classes, rosters, warnings = build_class_records(
        sections, courses_map, teacher_records, student_records, config
    )

    return GeneratorResult(
        students=student_records,
        staff=list(teacher_records.values()),
        courses=list(courses_map.values()),
        classes=classes,
        rosters=rosters,
        warnings=warnings,
    )
