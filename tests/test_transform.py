"""Tests for asm_generator.transform — LIB-03, LIB-05."""
import json
import pytest
from asm_generator.config import GeneratorConfig
from asm_generator.generator import generate
from asm_generator.transform import (
    build_student_records,
    build_student_records_monolith,
    build_teacher_records,
    build_course_records,
    make_roster_id,
    clean_name_part,
    extract_grade_level,
    slugify,
    expand_angebotsname,
)
from tests.conftest import make_monolith_csv


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config(tmp_path):
    """Minimal GeneratorConfig with real JSON files."""
    aliases_file = tmp_path / "aliases.json"
    subjects_file = tmp_path / "subjects.json"
    aliases_file.write_text(
        json.dumps([[["Claudine Cecile", "Cressole"], ["Marie", "Cressole"]]]),
        encoding="utf-8",
    )
    subjects_file.write_text(
        json.dumps({"Sp": "Sport", "E": "Englisch", "D": "Deutsch"}),
        encoding="utf-8",
    )
    return GeneratorConfig(
        location_id="sts_rissen",
        email_domain="rissen.hamburg.de",
        aliases_path=str(aliases_file),
        subjects_path=str(subjects_file),
    )


# ---------------------------------------------------------------------------
# LIB-05: externKey identity stability
# ---------------------------------------------------------------------------

def test_student_person_id_is_extern_key(config):
    """LIB-05: person_id must equal externKey regardless of name content."""
    students = [
        {"externKey": "8472", "longName": "Müller", "foreName": "Hans", "klasse.name": "5a"},
    ]
    records = build_student_records(students, config)
    assert records[0]["person_id"] == "8472"


def test_student_person_id_stable_on_name_change(config):
    """LIB-05: same externKey with different name → same person_id."""
    old_name = [{"externKey": "8472", "longName": "Müller", "foreName": "Hans", "klasse.name": "5a"}]
    new_name = [{"externKey": "8472", "longName": "Mueller", "foreName": "Johann", "klasse.name": "5a"}]

    records_before = build_student_records(old_name, config)
    records_after = build_student_records(new_name, config)

    assert records_before[0]["person_id"] == records_after[0]["person_id"] == "8472"


def test_student_email_derived_from_name(config):
    """Email is derived from name (not externKey) — still name-based for display."""
    students = [{"externKey": "9000", "longName": "Schmidt", "foreName": "Anna", "klasse.name": "6b"}]
    records = build_student_records(students, config)
    assert records[0]["email_address"] == "anna.schmidt@rissen.hamburg.de"


def test_student_email_still_generated_when_domain_missing(config):
    config.email_domain = ""
    students = [{"externKey": "9000", "longName": "Schmidt", "foreName": "Anna", "klasse.name": "6b"}]
    records = build_student_records(students, config)
    assert records[0]["email_address"] == "anna.schmidt@rissen.hamburg.de"


def test_student_grade_extracted(config):
    students = [{"externKey": "1", "longName": "X", "foreName": "Y", "klasse.name": "7c"}]
    records = build_student_records(students, config)
    assert records[0]["grade_level"] == "7"


# ---------------------------------------------------------------------------
# LIB-03: build_teacher_records — no file I/O
# ---------------------------------------------------------------------------

def test_teacher_records_no_io(config):
    """build_teacher_records must accept existing_staff as parameter, not read files."""
    sections = [
        {
            "teacher_abbr": "Mue",
            "teacher_first": "Anna",
            "teacher_last": "Müller",
            "angebotsname": "5a Sp",
            "rows": [],
        }
    ]
    # Pass empty existing_staff — should not attempt to open any file
    result = build_teacher_records(sections, [], config)
    assert ("Anna", "Müller") in result
    rec = result[("Anna", "Müller")]
    assert rec["person_id"] == "anna.mueller"
    assert rec["person_number"] == "Mue"
    assert rec["location_id"] == "sts_rissen"


def test_teacher_alias_resolved(config):
    """Teacher name from alias map is resolved to canonical form."""
    sections = [
        {
            "teacher_abbr": "Cre",
            "teacher_first": "Claudine Cecile",
            "teacher_last": "Cressole",
            "angebotsname": "8a Fr",
            "rows": [],
        }
    ]
    result = build_teacher_records(sections, [], config)
    # Alias maps ("Claudine Cecile", "Cressole") → ("Marie", "Cressole")
    assert ("Marie", "Cressole") in result
    assert ("Claudine Cecile", "Cressole") not in result


def test_teacher_existing_staff_preserved(config):
    """Existing staff records from pre-loaded list are retained."""
    existing_staff = [
        {
            "person_id": "max.mustermann",
            "person_number": "Mus",
            "first_name": "Max",
            "last_name": "Mustermann",
            "email_address": "max.mustermann@rissen.hamburg.de",
            "sis_username": "",
        }
    ]
    result = build_teacher_records([], existing_staff, config)
    assert ("Max", "Mustermann") in result
    assert result[("Max", "Mustermann")]["email_address"] == "max.mustermann@rissen.hamburg.de"


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

def test_clean_name_part_umlauts():
    assert clean_name_part("Müller") == "mueller"
    assert clean_name_part("Öztürk") == "oeztuerk"
    assert clean_name_part("Wäßler") == "waessler"


def test_extract_grade_level():
    assert extract_grade_level("5a") == "5"
    assert extract_grade_level("13c") == "13"
    assert extract_grade_level("Fremd 11") == "11"
    assert extract_grade_level("") == ""


def test_slugify():
    assert slugify("5a Sp") == "5a-sp"
    assert slugify("LB Gew") == "lb-gew"


def test_make_roster_id_is_stable_and_distinct():
    a1 = make_roster_id("cls-7a-d", "stu-1")
    a2 = make_roster_id("cls-7a-d", "stu-1")
    b = make_roster_id("cls-7a-d", "stu-2")
    assert a1 == a2
    assert a1 != b
    assert a1.startswith("roster-")


def test_expand_angebotsname():
    subjects = {"Sp": "Sport", "E": "Englisch"}
    assert expand_angebotsname("5a Sp", subjects) == "5a Sport"
    assert expand_angebotsname("7b E", subjects) == "7b Englisch"
    assert expand_angebotsname("Unbekannt", subjects) == "Unbekannt"


# ---------------------------------------------------------------------------
# LIB-07: config raises on missing JSON
# ---------------------------------------------------------------------------

def test_config_from_json_missing_raises(tmp_path):
    from asm_generator.config import GeneratorConfig
    with pytest.raises(FileNotFoundError, match="config file not found"):
        GeneratorConfig.from_json(str(tmp_path / "missing.json"))


def test_config_load_aliases_missing_raises(tmp_path):
    cfg = GeneratorConfig(
        location_id="x", email_domain="y",
        aliases_path=str(tmp_path / "no_aliases.json"),
        subjects_path=str(tmp_path / "no_subjects.json"),
    )
    with pytest.raises(FileNotFoundError, match="teacher aliases file not found"):
        cfg.load_aliases()


def test_build_student_records_monolith_uses_interne_id(config):
    rows = [
        {
            "interne_id": "uuid-1",
            "export_id": "exp-1",
            "vorname": "Max",
            "nachname": "Muster",
            "class_name": "8a",
            "email": "",
        }
    ]
    out = build_student_records_monolith(rows, config)
    assert out[0]["person_id"] == "uuid-1"
    assert out[0]["person_number"] == "uuid-1"
    assert out[0]["grade_level"] == "8"


def test_build_student_records_monolith_prefers_source_email(config):
    rows = [
        {
            "interne_id": "uuid-2",
            "export_id": "exp-2",
            "vorname": "Lea",
            "nachname": "Lenz",
            "class_name": "9c",
            "email": "lea.lenz@example.org",
        }
    ]
    config.email_domain = "rissen.hamburg.de"
    out = build_student_records_monolith(rows, config)
    assert out[0]["email_address"] == "lea.lenz@rissen.hamburg.de"


def test_build_student_records_monolith_prefers_rufname(config):
    rows = [
        {
            "interne_id": "uuid-3",
            "export_id": "exp-3",
            "vorname": "Maximilian",
            "rufname": "Max",
            "nachname": "Muster",
            "class_name": "7a",
            "email": "",
        }
    ]
    out = build_student_records_monolith(rows, config)
    assert out[0]["first_name"] == "Max"


def test_build_teacher_records_cleans_first_name_symbols(config):
    sections = [
        {
            "teacher_abbr": "Mst",
            "teacher_first": "An(na):2",
            "teacher_last": "Muster",
            "angebotsname": "7a D",
            "rows": [],
        }
    ]
    result = build_teacher_records(sections, [], config)
    assert ("Anna", "Muster") in result


def test_build_teacher_records_skips_empty_placeholder_teacher(config):
    sections = [
        {
            "teacher_abbr": "",
            "teacher_first": "",
            "teacher_last": "",
            "angebotsname": "7a D",
            "rows": [],
        }
    ]
    result = build_teacher_records(sections, [], config)
    assert result == {}


def test_build_teacher_records_collision_reuses_pid_without_suffix(config):
    sections = [
        {
            "teacher_abbr": "A1",
            "teacher_first": "Jan",
            "teacher_last": "Meyer",
            "angebotsname": "7a D",
            "rows": [],
        },
        {
            "teacher_abbr": "A2",
            "teacher_first": "Jan Karl",
            "teacher_last": "Meyer",
            "angebotsname": "7b D",
            "rows": [],
        },
    ]
    result = build_teacher_records(sections, [], config)
    pids = {v["person_id"] for v in result.values()}
    assert pids == {"jan.meyer"}
    assert all(not pid.endswith("-2") for pid in pids)


def test_generate_monolith_mode_outputs_asm_tables(tmp_path, config):
    monolith = tmp_path / "mono.csv"
    monolith.write_text(
        make_monolith_csv(
            [
                {
                    "Nachname": "Muster",
                    "Vorname": "Max",
                    "Klassennamen": "6a",
                    "Angebote": "6a Sp-2025/2026-Angebot-rissen",
                    "E-Mail-Adressen der weiteren Schulen": "max@example.org",
                    "Rolle": "Lernende",
                    "Interne ID": "stu-1",
                    "Export ID": "exp-stu-1",
                },
                {
                    "Nachname": "Lehrer",
                    "Vorname": "Lena",
                    "Kürzel": "Lhr",
                    "Angebote": "6a Sp-2025/2026-Angebot-rissen",
                    "Rolle": "Lehrkraft",
                    "Interne ID": "tea-1",
                    "Export ID": "exp-tea-1",
                },
            ]
        ),
        encoding="utf-8",
    )
    config.input_mode = "monolith"
    config.target_school_year = "2025/2026"
    result = generate(config, [], [], existing_staff=[], input_mode="monolith", monolith_paths=[monolith])
    assert len(result.students) == 1
    assert len(result.staff) == 1
    assert len(result.courses) == 1
    assert len(result.classes) == 1
    assert len(result.rosters) == 1
