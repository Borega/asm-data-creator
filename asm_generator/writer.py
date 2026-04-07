"""I/O functions — the only module in asm_generator that touches the filesystem."""
from __future__ import annotations
import csv
import os
from pathlib import Path
from .config import GeneratorResult


def write_to_zip(result: GeneratorResult, output_path) -> None:
    """Pack approved output CSVs into a ZIP file at output_path.

    Implementation deferred to Phase 3. This stub exists so Phase 2 imports work.
    The GUI Export pipeline (EXP-01 through EXP-06) will implement this.
    """
    raise NotImplementedError("write_to_zip is implemented in Phase 3")


def write_csv_files(result: GeneratorResult, output_dir=".") -> None:
    """Write all five ASM CSVs to output_dir.

    Used by the generate_asm.py shim for standalone runs.
    All files use UTF-8 encoding without BOM (ASM requirement) and QUOTE_ALL.
    """
    output_dir = Path(output_dir)

    def _write(filename: str, fieldnames: list, rows: list) -> None:
        path = output_dir / filename
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=fieldnames,
                quoting=csv.QUOTE_ALL,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(rows)

    _write("students.csv", [
        "person_id", "person_number", "first_name", "middle_name",
        "last_name", "grade_level", "email_address", "sis_username",
        "password_policy", "location_id",
    ], result.students)

    _write("staff.csv", [
        "person_id", "person_number", "first_name", "middle_name",
        "last_name", "email_address", "sis_username", "location_id",
    ], result.staff)

    _write("courses.csv", [
        "course_id", "course_number", "course_name", "location_id",
    ], result.courses)

    _write("classes.csv", [
        "class_id", "class_number", "course_id",
        "instructor_id", "instructor_id_2", "instructor_id_3", "location_id",
    ], result.classes)

    _write("rosters.csv", [
        "roster_id", "class_id", "student_id",
    ], result.rosters)
