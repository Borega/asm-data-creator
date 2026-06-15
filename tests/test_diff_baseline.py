"""Tests for diff baseline loading from CSV/ZIP sources."""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

import pytest

from asm_generator.config import GeneratorConfig
from diff_baseline import load_baseline_from_csv_source
from tests.conftest import make_monolith_csv


_REQUIRED_FILES = ("students.csv", "staff.csv", "courses.csv", "classes.csv", "rosters.csv")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_baseline_dir(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _write_csv(
        directory / "students.csv",
        ["person_id", "person_number", "first_name", "middle_name", "last_name", "grade_level", "email_address", "sis_username", "password_policy", "location_id"],
        [{"person_id": "stu-1", "first_name": "Max", "last_name": "Muster", "person_number": "stu-1", "middle_name": "", "grade_level": "6", "email_address": "max.muster@example.org", "sis_username": "", "password_policy": "", "location_id": "loc-001"}],
    )
    _write_csv(
        directory / "staff.csv",
        ["person_id", "person_number", "first_name", "last_name", "email_address", "sis_username", "location_id"],
        [{"person_id": "teacher.one", "person_number": "T1", "first_name": "Teacher", "last_name": "One", "email_address": "teacher.one@example.org", "sis_username": "", "location_id": "loc-001"}],
    )
    _write_csv(
        directory / "courses.csv",
        ["course_id", "course_number", "course_name", "location_id"],
        [{"course_id": "course-1", "course_number": "6a Ma", "course_name": "Mathematik 6a", "location_id": "loc-001"}],
    )
    _write_csv(
        directory / "classes.csv",
        ["class_id", "class_number", "course_id", "instructor_id", "instructor_id_2", "instructor_id_3", "location_id"],
        [{"class_id": "class-1", "class_number": "6a Ma", "course_id": "course-1", "instructor_id": "teacher.one", "instructor_id_2": "", "instructor_id_3": "", "location_id": "loc-001"}],
    )
    _write_csv(
        directory / "rosters.csv",
        ["roster_id", "class_id", "student_id"],
        [{"roster_id": "r-1", "class_id": "class-1", "student_id": "stu-1"}],
    )


def _make_config(tmp_path: Path) -> GeneratorConfig:
    aliases_path = tmp_path / "aliases.json"
    subjects_path = tmp_path / "subjects.json"
    aliases_path.write_text(json.dumps([]), encoding="utf-8")
    subjects_path.write_text(json.dumps({}), encoding="utf-8")

    return GeneratorConfig(
        location_id="loc-001",
        email_domain="example.org",
        aliases_path=str(aliases_path),
        subjects_path=str(subjects_path),
        input_mode="schuldock",
        target_school_year="2025/2026",
    )


def test_load_baseline_from_csv_directory(tmp_path: Path):
    baseline_dir = tmp_path / "baseline"
    _write_baseline_dir(baseline_dir)

    result = load_baseline_from_csv_source(baseline_dir)

    assert len(result.students) == 1
    assert len(result.staff) == 1
    assert len(result.courses) == 1
    assert len(result.classes) == 1
    assert len(result.rosters) == 1


def test_load_baseline_from_csv_file_uses_parent_directory(tmp_path: Path):
    baseline_dir = tmp_path / "baseline"
    _write_baseline_dir(baseline_dir)

    result = load_baseline_from_csv_source(baseline_dir / "students.csv")

    assert len(result.students) == 1
    assert result.staff[0]["person_id"] == "teacher.one"


def test_load_baseline_from_zip(tmp_path: Path):
    baseline_dir = tmp_path / "baseline"
    _write_baseline_dir(baseline_dir)

    zip_path = tmp_path / "baseline.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in _REQUIRED_FILES:
            zf.write(baseline_dir / name, arcname=name)

    result = load_baseline_from_csv_source(zip_path)

    assert len(result.students) == 1
    assert result.classes[0]["class_id"] == "class-1"


def test_load_baseline_from_monolith_csv_with_extra_columns(tmp_path: Path):
    # Create a regular ASM bundle in the same parent folder to ensure
    # monolith detection wins over "load parent directory" fallback.
    _write_baseline_dir(tmp_path)

    monolith = tmp_path / "Benutzer-Daten(2).csv"
    monolith.write_text(
        "\n".join(
            [
                "Nachname;Nachname Kurzform;Vorname;Rufname;Geburtstag;Geschlecht;Kürzel;Schulen;Stammschule;Klassen;Klassennamen;Angebote;Manuelle Gruppen;Anmeldekennung;E-Mail-Adressen der weiteren Schulen;Status;Rolle;Quelle;Interne ID;Export ID;Gültig ab;Gültig bis;Löschdatum",
                "Muster;;Maximilian;Max;01.01.2012;Männlich;;example;example;6a-2025/2026-Klasse-example;6a;6a Ma-2025/2026-Angebot-example;;;max.muster@example.org;Aktiv;Lernende;DiViS;mono-stu-1;mono-exp-stu-1;01.08.2025;31.07.2032;28.01.2033",
                "Lehrer;;Lena;;01.01.1980;Weiblich;Lhr;example;example;;;6a Ma-2025/2026-Angebot-example;;;lena.lehrer@example.org;Aktiv;Lehrkraft;DiViS;mono-tea-1;mono-exp-tea-1;01.08.2025;31.07.2032;28.01.2033",
            ]
        ),
        encoding="utf-8",
    )

    result = load_baseline_from_csv_source(monolith, config=_make_config(tmp_path))

    assert [row["person_id"] for row in result.students] == ["mono-stu-1"]
    assert [row["person_id"] for row in result.staff] == ["lena.lehrer"]
    assert [row["course_number"] for row in result.courses] == ["6a Ma"]
    assert len(result.classes) == 1
    assert len(result.rosters) == 1


def test_load_baseline_from_monolith_csv_requires_config(tmp_path: Path):
    monolith = tmp_path / "Benutzer-Daten(2).csv"
    monolith.write_text(make_monolith_csv([]), encoding="utf-8")

    with pytest.raises(ValueError, match="requires generator config"):
        load_baseline_from_csv_source(monolith)



def test_load_baseline_missing_required_files_raises(tmp_path: Path):
    baseline_dir = tmp_path / "incomplete"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        baseline_dir / "students.csv",
        ["person_id"],
        [{"person_id": "stu-1"}],
    )

    with pytest.raises(FileNotFoundError, match="missing required files"):
        load_baseline_from_csv_source(baseline_dir)


def test_load_baseline_rejects_unsupported_source(tmp_path: Path):
    source = tmp_path / "baseline.txt"
    source.write_text("not supported", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported baseline source"):
        load_baseline_from_csv_source(source)
