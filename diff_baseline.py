"""Load diff baselines from exported ASM CSV datasets."""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from asm_generator.config import GeneratorConfig, GeneratorResult
from asm_generator.parsers import parse_monolith
from asm_generator.transform import (
    build_class_records,
    build_course_records,
    build_student_records_monolith,
    build_teacher_records,
)

_REQUIRED_FILES = ("students.csv", "staff.csv", "courses.csv", "classes.csv", "rosters.csv")
_MONOLITH_HEADER_MARKERS = {
    "Nachname",
    "Vorname",
    "Rolle",
    "Angebote",
    "Interne ID",
    "Export ID",
}


def _read_csv_text(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _read_csv_file(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader]


def _read_first_line(path: Path) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path, encoding=encoding, newline="") as fh:
                return (fh.readline() or "").strip()
        except UnicodeDecodeError:
            continue
    return ""


def _looks_like_monolith_csv(path: Path) -> bool:
    header_line = _read_first_line(path)
    if ";" not in header_line:
        return False
    columns = {cell.strip() for cell in header_line.split(";") if cell.strip()}
    return _MONOLITH_HEADER_MARKERS.issubset(columns)


def _load_from_directory(directory: Path) -> GeneratorResult:
    missing = [name for name in _REQUIRED_FILES if not (directory / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Baseline CSV folder is missing required files: {', '.join(missing)}"
        )

    students = _read_csv_file(directory / "students.csv")
    staff = _read_csv_file(directory / "staff.csv")
    courses = _read_csv_file(directory / "courses.csv")
    classes = _read_csv_file(directory / "classes.csv")
    rosters = _read_csv_file(directory / "rosters.csv")

    return GeneratorResult(
        students=students,
        staff=staff,
        courses=courses,
        classes=classes,
        rosters=rosters,
        warnings=[],
    )


def _load_from_zip(zip_path: Path) -> GeneratorResult:
    with zipfile.ZipFile(zip_path, "r") as zf:
        name_map = {Path(name).name.lower(): name for name in zf.namelist()}

        missing = [name for name in _REQUIRED_FILES if name.lower() not in name_map]
        if missing:
            raise FileNotFoundError(
                f"Baseline ZIP is missing required files: {', '.join(missing)}"
            )

        def _read_member(required_name: str) -> list[dict[str, str]]:
            member_name = name_map[required_name.lower()]
            with zf.open(member_name, "r") as member:
                text = member.read().decode("utf-8-sig")
            return _read_csv_text(text)

        students = _read_member("students.csv")
        staff = _read_member("staff.csv")
        courses = _read_member("courses.csv")
        classes = _read_member("classes.csv")
        rosters = _read_member("rosters.csv")

    return GeneratorResult(
        students=students,
        staff=staff,
        courses=courses,
        classes=classes,
        rosters=rosters,
        warnings=[],
    )


def _load_from_monolith_csv(path: Path, config: GeneratorConfig) -> GeneratorResult:
    parsed = parse_monolith([path], config.target_school_year)
    student_records = build_student_records_monolith(parsed["students"], config)

    teacher_records = build_teacher_records(
        parsed["sections"],
        existing_staff=[],
        config=config,
        monolith_staff=parsed.get("teachers", []),
    )
    courses_map = build_course_records(parsed["sections"], config)
    classes, rosters, build_warnings = build_class_records(
        parsed["sections"],
        courses_map,
        teacher_records,
        student_records,
        config,
    )

    warnings = list(parsed.get("warnings", []))
    warnings.extend(build_warnings)

    return GeneratorResult(
        students=student_records,
        staff=list(teacher_records.values()),
        courses=list(courses_map.values()),
        classes=classes,
        rosters=rosters,
        warnings=warnings,
    )


def load_baseline_from_csv_source(
    path: str | Path,
    *,
    config: GeneratorConfig | None = None,
) -> GeneratorResult:
    """Load a full diff baseline from CSV/ZIP/monolith sources.

    Accepted inputs:
    - Path to a directory containing students/staff/courses/classes/rosters CSV files
    - Path to a ZIP containing those CSV files
    - Path to one of those CSV files (uses its parent directory)
    - Path to a Schuldock monolith users CSV (e.g. Benutzer-Daten(2).csv)
      when ``config`` is provided.
    """
    source = Path(path)

    if source.is_dir():
        return _load_from_directory(source)

    if source.is_file() and source.suffix.lower() == ".zip":
        return _load_from_zip(source)

    if source.is_file() and source.suffix.lower() == ".csv":
        if _looks_like_monolith_csv(source):
            if config is None:
                raise ValueError(
                    "Monolith baseline CSV requires generator config for alias/subject resolution."
                )
            return _load_from_monolith_csv(source, config)

        return _load_from_directory(source.parent)

    raise ValueError(
        "Unsupported baseline source. Select a CSV file, a ZIP file, or a folder containing ASM CSV files."
    )
