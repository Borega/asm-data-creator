"""I/O functions — the only module in asm_generator that touches the filesystem."""
from __future__ import annotations
import csv
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from .config import GeneratorResult
from .transform import make_person_id_parts, clean_name_part


_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "asmtemplates"


def _load_location_name_map() -> dict[str, str]:
    """Load optional location_id -> location_name mappings from repository locations.csv."""
    mapping_path = Path(__file__).resolve().parent.parent / "locations.csv"
    if not mapping_path.is_file():
        return {}

    result: dict[str, str] = {}
    with open(mapping_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lid = (row.get("location_id", "") or "").strip()
            if not lid:
                continue
            lname = (row.get("location_name", "") or "").strip() or lid
            result[lid] = lname
    return result


def _fieldnames_from_template(filename: str, fallback: list[str]) -> list[str]:
    """Read CSV header from asmtemplates/<filename>; fallback if unavailable."""
    template_path = _TEMPLATE_DIR / filename
    if not template_path.is_file():
        return fallback
    with open(template_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if row:
                return row
    return fallback


def _normalize_rows(fieldnames: list[str], rows: list[dict]) -> list[dict]:
    """Normalize rows to template fieldnames and convert None/missing to empty strings."""
    normalized: list[dict] = []
    for row in rows:
        out: dict[str, str] = {}
        for field in fieldnames:
            value = row.get(field, "")
            if value is None:
                out[field] = ""
            elif isinstance(value, str):
                out[field] = value.replace("\r", " ").replace("\n", " ")
            else:
                out[field] = str(value)
        normalized.append(out)
    return normalized


def _build_location_rows(result: GeneratorResult) -> list[dict]:
    """Build locations.csv rows from location IDs used by exported tables."""
    used_ids: set[str] = set()
    for rows in (result.students, result.staff, result.courses, result.classes):
        for row in rows:
            lid = (row.get("location_id", "") or "").strip()
            if lid:
                used_ids.add(lid)

    name_map = _load_location_name_map()
    return [
        {
            "location_id": lid,
            "location_name": name_map.get(lid, lid),
        }
        for lid in sorted(used_ids)
    ]


def _sanitize_staff_rows(rows: list[dict]) -> list[dict]:
    """Ensure exported staff rows always contain a valid person_id.

    Also deduplicates colliding person_ids by merging into a single row,
    preferring non-empty fields from later rows.
    """

    def _fallback_pid(row: dict, idx: int) -> str:
        first = (row.get("first_name", "") or "").strip()
        last = (row.get("last_name", "") or "").strip()
        fp, lp = make_person_id_parts(first, last)
        if fp and lp:
            return f"{fp}.{lp}"
        if lp:
            return lp
        if fp:
            return fp
        pn = clean_name_part((row.get("person_number", "") or "").strip())
        if pn:
            return f"staff.{pn}"
        return f"staff.unknown-{idx}"

    merged: dict[str, dict] = {}
    for idx, raw in enumerate(rows, start=1):
        row = dict(raw)
        pid = (row.get("person_id", "") or "").strip() or _fallback_pid(row, idx)
        row["person_id"] = pid

        if pid in merged:
            existing = merged[pid]
            for k, v in row.items():
                if (v or "").strip() and not (existing.get(k, "") or "").strip():
                    existing[k] = v
            continue

        merged[pid] = row

    return list(merged.values())


def write_to_zip(result: GeneratorResult, output_path) -> None:
    """Pack approved output CSVs into a flat ZIP file at output_path.

    Always includes all six files
    (students, staff, courses, classes, rosters, locations)
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
            template_fields = _fieldnames_from_template(filename, fieldnames)
            clean_rows = _normalize_rows(template_fields, rows)
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=template_fields,
                    quoting=csv.QUOTE_ALL,
                    extrasaction="ignore",
                )
                writer.writeheader()
                writer.writerows(clean_rows)
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
            ], _sanitize_staff_rows(result.staff)),
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
            _write_csv("locations.csv", [
                "location_id", "location_name",
            ], _build_location_rows(result)),
        ]

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for csv_path in csv_files:
                zf.write(csv_path, arcname=os.path.basename(csv_path))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def write_csv_files(result: GeneratorResult, output_dir=".") -> None:
    """Write all six ASM CSVs to output_dir.

    Used by the generate_asm.py shim for standalone runs.
    All files use UTF-8 encoding without BOM (ASM requirement) and QUOTE_ALL.
    """
    output_dir = Path(output_dir)

    def _write(filename: str, fieldnames: list, rows: list) -> None:
        path = output_dir / filename
        template_fields = _fieldnames_from_template(filename, fieldnames)
        clean_rows = _normalize_rows(template_fields, rows)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=template_fields,
                quoting=csv.QUOTE_ALL,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(clean_rows)

    _write("students.csv", [
        "person_id", "person_number", "first_name", "middle_name",
        "last_name", "grade_level", "email_address", "sis_username",
        "password_policy", "location_id",
    ], result.students)

    _write("staff.csv", [
        "person_id", "person_number", "first_name", "middle_name",
        "last_name", "email_address", "sis_username", "location_id",
    ], _sanitize_staff_rows(result.staff))

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

    _write("locations.csv", [
        "location_id", "location_name",
    ], _build_location_rows(result))
