"""I/O functions — the only module in asm_generator that touches the filesystem."""
from __future__ import annotations
import csv
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from .config import GeneratorResult


def write_to_zip(result: GeneratorResult, output_path) -> None:
    """Pack approved output CSVs into a flat ZIP file at output_path.

    Always includes all five files (students, staff, courses, classes, rosters)
    even if the corresponding list is empty (headers only). CSV files use
    UTF-8 encoding, no BOM, QUOTE_ALL, and newline="" to prevent double-CR on
    Windows.

    Strategy: write CSVs to a temp directory, pack into ZIP at output_path,
    then clean up the temp directory.

    Raises PermissionError if output_path cannot be written.
    Raises OSError for other I/O failures.
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        def _write_csv(filename: str, fieldnames: list, rows: list) -> str:
            path = os.path.join(tmp_dir, filename)
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=fieldnames,
                    quoting=csv.QUOTE_ALL,
                    extrasaction="ignore",
                )
                writer.writeheader()
                writer.writerows(rows)
            return path

        csv_files = [
            _write_csv("students.csv", [
                "person_id", "person_number", "first_name", "middle_name",
                "last_name", "grade_level", "email_address", "sis_username",
                "password_policy", "location_id",
            ], result.students),
            _write_csv("staff.csv", [
                "person_id", "person_number", "first_name", "middle_name",
                "last_name", "email_address", "sis_username", "location_id",
            ], result.staff),
            _write_csv("courses.csv", [
                "course_id", "course_number", "course_name", "location_id",
            ], result.courses),
            _write_csv("classes.csv", [
                "class_id", "class_number", "course_id",
                "instructor_id", "instructor_id_2", "instructor_id_3", "location_id",
            ], result.classes),
            _write_csv("rosters.csv", [
                "roster_id", "class_id", "student_id",
            ], result.rosters),
        ]

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for csv_path in csv_files:
                zf.write(csv_path, arcname=os.path.basename(csv_path))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


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
