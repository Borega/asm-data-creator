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
        json.dumps([[["Clara Cecile", "Probe"], ["Marie", "Probe"]]]),
        encoding="utf-8",
    )
    subjects_file.write_text(
        json.dumps({"Sp": "Sport", "E": "Englisch", "D": "Deutsch"}),
        encoding="utf-8",
    )
    return GeneratorConfig(
        location_id="loc-001",
        email_domain="example.org",
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
    assert records[0]["email_address"] == "anna.schmidt@example.org"


def test_generation_refuses_when_the_email_domain_is_missing(config):
    """Was: a blank domain silently produced rissen.hamburg.de addresses.

    That only looked harmless while the domain was hardcoded. For any other
    school it means issuing accounts on a domain they do not own, discovered
    after the accounts exist — so a blank domain is now a hard error.
    """
    config.email_domain = ""
    students = [{"externKey": "9000", "longName": "Schmidt", "foreName": "Anna", "klasse.name": "6b"}]

    with pytest.raises(ValueError, match="No email domain configured"):
        build_student_records(students, config)


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
    assert rec["location_id"] == "loc-001"


def test_teacher_alias_resolved(config):
    """Teacher name from alias map is resolved to canonical form."""
    sections = [
        {
            "teacher_abbr": "Pro",
            "teacher_first": "Clara Cecile",
            "teacher_last": "Probe",
            "angebotsname": "8a Fr",
            "rows": [],
        }
    ]
    result = build_teacher_records(sections, [], config)
    # Alias maps ("Clara Cecile", "Probe") → ("Marie", "Probe")
    assert ("Marie", "Probe") in result
    assert ("Clara Cecile", "Probe") not in result


def test_monolith_style_teacher_aliases_collapse_duplicates_from_existing_staff(tmp_path):
    aliases_file = tmp_path / "aliases.json"
    subjects_file = tmp_path / "subjects.json"
    aliases_file.write_text(
        json.dumps(
            [
                [["Anja", "Mustermann"], ["Anja-Michelle", "Mustermann"]],
                [["Berta Katharina", "Beispiel"], ["Katharina", "Beispiel"]],
                [["Clara Cecile", "Probe"], ["Marie", "Probe"]],
                [["Marielena", "Musterfrau"], ["Elena", "Musterfrau"]],
            ]
        ),
        encoding="utf-8",
    )
    subjects_file.write_text(json.dumps({"Ma": "Mathematik"}), encoding="utf-8")

    cfg = GeneratorConfig(
        location_id="loc-001",
        email_domain="example.org",
        aliases_path=str(aliases_file),
        subjects_path=str(subjects_file),
    )

    existing_staff = [
        {
            "first_name": "Anja",
            "last_name": "Mustermann",
            "person_id": "",
            "person_number": "",
            "email_address": "",
            "sis_username": "",
        },
        {
            "first_name": "Katharina",
            "last_name": "Beispiel",
            "person_id": "",
            "person_number": "Ts",
            # Foreign domain: must be rejected and regenerated to the configured domain.
            "email_address": "katharina.beispiel@external.example",
            "sis_username": "",
        },
        {
            "first_name": "Marie",
            "last_name": "Probe",
            "person_id": "",
            "person_number": "Cre",
            "email_address": "marie.probe@example.org",
            "sis_username": "",
        },
        {
            "first_name": "Elena",
            "last_name": "Musterfrau",
            "person_id": "",
            "person_number": "Sn",
            "email_address": "elena.musterfrau@example.org",
            "sis_username": "",
        },
    ]

    sections = [
        {
            "teacher_abbr": "Blo",
            "teacher_first": "Anja-Michelle",
            "teacher_last": "Mustermann",
            "angebotsname": "5a Rel",
            "rows": [],
        },
        {
            "teacher_abbr": "Ts",
            "teacher_first": "Berta Katharina",
            "teacher_last": "Beispiel",
            "angebotsname": "6a BKu",
            "rows": [],
        },
        {
            "teacher_abbr": "Cre",
            "teacher_first": "Clara Cecile",
            "teacher_last": "Probe",
            "angebotsname": "8c Ma",
            "rows": [],
        },
        {
            "teacher_abbr": "Sn",
            "teacher_first": "Marielena",
            "teacher_last": "Musterfrau",
            "angebotsname": "7d Ma",
            "rows": [],
        },
    ]

    result = build_teacher_records(sections, existing_staff, cfg)

    assert set(result.keys()) == {
        ("Anja-Michelle", "Mustermann"),
        ("Katharina", "Beispiel"),
        ("Marie", "Probe"),
        ("Elena", "Musterfrau"),
    }
    assert result[("Anja-Michelle", "Mustermann")]["email_address"] == "anja-michelle.mustermann@example.org"
    assert result[("Katharina", "Beispiel")]["email_address"] == "katharina.beispiel@example.org"
    assert result[("Marie", "Probe")]["email_address"] == "marie.probe@example.org"
    assert result[("Elena", "Musterfrau")]["email_address"] == "elena.musterfrau@example.org"


def test_teacher_existing_staff_preserved(config):
    """Existing staff records from pre-loaded list are retained."""
    existing_staff = [
        {
            "person_id": "max.mustermann",
            "person_number": "Mus",
            "first_name": "Max",
            "last_name": "Mustermann",
            "email_address": "max.mustermann@example.org",
            "sis_username": "",
        }
    ]
    result = build_teacher_records([], existing_staff, config)
    assert ("Max", "Mustermann") in result
    assert result[("Max", "Mustermann")]["email_address"] == "max.mustermann@example.org"


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


def test_expand_angebotsname_keeps_parallel_group_and_level_markers():
    """'11 Phy 1' and '11 Phy 2' must stay tellable apart after expansion."""
    subjects = {"Phy": "Physik", "D": "Deutsch"}
    assert expand_angebotsname("11 Phy 1", subjects) == "11 Physik 1"
    assert expand_angebotsname("11 Phy 2", subjects) == "11 Physik 2"
    assert expand_angebotsname("12 D 2 eA", subjects) == "12 Deutsch 2 eA"
    assert expand_angebotsname("12 D 2 gA", subjects) == "12 Deutsch 2 gA"


def test_expand_angebotsname_resolves_studienstufe_suffix():
    """'Bio_SS' is Biologie in the Studienstufe (years 12-13)."""
    subjects = {"Bio": "Biologie", "E": "Englisch"}
    assert expand_angebotsname("12-13 Bio_SS", subjects) == "12-13 Biologie Studienstufe"
    assert expand_angebotsname("13c E_SS 3", subjects) == "13c Englisch Studienstufe 3"


def test_expand_angebotsname_expands_longest_known_subject_prefix():
    """'L:AB Holz Roth' is Arbeitslehre plus a workshop and a teacher."""
    subjects = {"L:AB": "Arbeitslehre", "LB Gew": "Lernbereich Gesellschaft"}
    assert expand_angebotsname("6 L:AB Holz Roth", subjects) == "6 Arbeitslehre Holz Roth"
    # The two-token key must win over any shorter accidental match.
    assert expand_angebotsname("8a LB Gew", subjects) == "8a Lernbereich Gesellschaft"


def test_expand_angebotsname_expands_subject_led_offers():
    """Offers with no grade lead with the subject: 'Holz Roth HJ1', 'Spo1 Badminton'."""
    subjects = {"Holz": "Arbeitslehre Holz", "Spo1": "Sport", "Ma": "Mathematik"}
    assert expand_angebotsname("Holz Roth HJ1", subjects) == "Arbeitslehre Holz Roth HJ1"
    assert expand_angebotsname("Spo1 Badminton", subjects) == "Sport Badminton"
    # A real '<class> <subject>' must not be re-read as subject-led.
    assert expand_angebotsname("7a Ma", subjects) == "7a Mathematik"


def test_build_teacher_records_splits_full_given_names(tmp_path):
    """Schuldock now exports every given name; only the first belongs in first_name."""
    aliases = tmp_path / "aliases.json"
    aliases.write_text("[]", encoding="utf-8")
    subjects = tmp_path / "subjects.json"
    subjects.write_text("{}", encoding="utf-8")
    config = GeneratorConfig(
        location_id="loc", email_domain="rissen.hamburg.de",
        aliases_path=str(aliases), subjects_path=str(subjects),
    )

    teachers = build_teacher_records(
        [],
        [],
        config,
        monolith_staff=[{
            "first_name": "Jana Hannerl Astrid",
            "last_name": "Ahrens",
            "person_number": "And",
            "_source": "monolith",
        }],
    )

    rec = next(iter(teachers.values()))
    assert rec["first_name"] == "Jana"
    assert rec["middle_name"] == "Hannerl Astrid"
    # person_id has always used the leading token, so it must not move.
    assert rec["person_id"] == "jana.ahrens"


def test_drop_duplicate_classes_collapses_hash_prefixed_twins():
    """'#Holz Roth HJ1' and 'Holz Roth HJ1' slugify to one id — ASM rejects dupes."""
    from asm_generator.transform import drop_duplicate_classes

    courses = [
        {"course_id": "holz-roth-hj1", "course_number": "#Holz Roth HJ1"},
        {"course_id": "holz-roth-hj1", "course_number": "Holz Roth HJ1"},
        {"course_id": "5a-ma", "course_number": "5a Ma"},
    ]
    classes = [
        {"class_id": "cls-holz-roth-hj1", "class_number": "#Holz Roth HJ1"},
        {"class_id": "cls-holz-roth-hj1", "class_number": "Holz Roth HJ1"},
        {"class_id": "cls-5a-ma", "class_number": "5a Ma"},
    ]
    rosters = [
        {"roster_id": "r1", "class_id": "cls-holz-roth-hj1", "student_id": "s1"},
        {"roster_id": "r2", "class_id": "cls-5a-ma", "student_id": "s1"},
    ]

    courses, classes, out_rosters, warnings = drop_duplicate_classes(courses, classes, rosters)

    assert [c["course_number"] for c in courses] == ["Holz Roth HJ1", "5a Ma"]
    assert [c["class_number"] for c in classes] == ["Holz Roth HJ1", "5a Ma"]
    assert out_rosters == rosters, "collapsing duplicate ids must not drop enrolments"
    assert len(warnings) == 2  # one for the course, one for the class


def test_drop_duplicate_classes_leaves_distinct_ids_alone():
    """A form group shares students across subjects — those must never merge."""
    from asm_generator.transform import drop_duplicate_classes

    courses = [
        {"course_id": "5a-ma", "course_number": "5a Ma"},
        {"course_id": "5a-d", "course_number": "5a D"},
    ]
    classes = [
        {"class_id": "cls-5a-ma", "class_number": "5a Ma"},
        {"class_id": "cls-5a-d", "class_number": "5a D"},
    ]
    rosters = [
        {"roster_id": "r1", "class_id": "cls-5a-ma", "student_id": "s1"},
        {"roster_id": "r2", "class_id": "cls-5a-d", "student_id": "s1"},
    ]

    out = drop_duplicate_classes(courses, classes, rosters)

    assert out[0] == courses and out[1] == classes and out[2] == rosters
    assert out[3] == []


def test_expand_angebotsname_drops_leading_hash_decoration():
    """'#'/'##'/'###' is Schuldock decoration; '#10 Phil I' is grade 10."""
    subjects = {"Phil": "Philosophie", "Holz": "Arbeitslehre Holz"}
    assert expand_angebotsname("#10 Phil I", subjects) == "10 Philosophie I"
    assert expand_angebotsname("###FORDER 9 NAWI", subjects) == "FORDER 9 NAWI"
    assert expand_angebotsname("#Holz Roth HJ1", subjects) == "Arbeitslehre Holz Roth HJ1"


def test_expand_angebotsname_matches_subjects_case_insensitively():
    """The source spells one token both ways: '7 WP1 Fra' but '7 Wp1 Spa'."""
    subjects = {"WP1 Spa": "Spanisch", "WP1 Fra": "Französisch"}
    assert expand_angebotsname("7 Wp1 Spa", subjects) == "7 Spanisch"
    assert expand_angebotsname("7 WP1 Fra", subjects) == "7 Französisch"


def test_expand_angebotsname_keeps_unknown_underscore_suffix_verbatim():
    """'Mu_VS' stays honest as 'Musik VS' rather than inventing a stage name."""
    subjects = {"Mu": "Musik"}
    assert expand_angebotsname("12-13 Mu_VS", subjects) == "12-13 Musik VS"
    assert expand_angebotsname("10 Mu_5-10", subjects) == "10 Musik 5-10"


def test_expand_angebotsname_leaves_unknown_subjects_untouched():
    """An unrecognised subject must never be half-decoded or guessed at."""
    subjects = {"Bio": "Biologie"}
    for name in ("9a L:AB", "7 WP1 Fra", "11 Che 1 LEH", "12-13 Mu_VS"):
        assert expand_angebotsname(name, subjects) == name


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
            # Source email on a foreign domain: local-part kept, domain swapped.
            "email": "lnz.student17@external.example",
        }
    ]
    config.email_domain = "example.org"
    out = build_student_records_monolith(rows, config)
    assert out[0]["email_address"] == "lnz.student17@example.org"


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


def test_build_student_records_monolith_populates_middle_name_and_sis_username(config):
    rows = [
        {
            "interne_id": "uuid-4",
            "export_id": "exp-4",
            "vorname": "Leon Paul",
            "rufname": "Leon",
            "nachname": "Beispiel",
            "class_name": "6a",
            "email": "",
            "anmeldekennung": "leon.beispiel@example.org",
        }
    ]

    out = build_student_records_monolith(rows, config)

    assert out[0]["first_name"] == "Leon"
    assert out[0]["middle_name"] == "Paul"
    assert out[0]["sis_username"] == "leon.beispiel@example.org"
    assert out[0]["email_address"] == "leon.beispiel@example.org"


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
                    "Angebote": "6a Sp-2025/2026-Angebot-example",
                    "Anmeldekennung": "max.login",
                    "E-Mail-Adressen der weiteren Schulen": "max@example.org",
                    "Rolle": "Lernende",
                    "Interne ID": "stu-1",
                    "Export ID": "exp-stu-1",
                },
                {
                    "Nachname": "Lehrer",
                    "Vorname": "Lena",
                    "Kürzel": "Lhr",
                    "Angebote": "6a Sp-2025/2026-Angebot-example",
                    "Anmeldekennung": "lena.login",
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
    assert result.students[0]["sis_username"] == "max.login"
    assert result.staff[0]["sis_username"] == "lena.login"


def test_generate_monolith_includes_teachers_without_current_year_offers(tmp_path, config):
    monolith = tmp_path / "mono-teachers.csv"
    monolith.write_text(
        make_monolith_csv(
            [
                {
                    "Nachname": "Muster",
                    "Vorname": "Max",
                    "Klassennamen": "6a",
                    "Angebote": "6a Sp-2025/2026-Angebot-example",
                    "Rolle": "Lernende",
                    "Interne ID": "stu-1",
                    "Export ID": "exp-stu-1",
                },
                {
                    "Nachname": "Lehrer",
                    "Vorname": "Lena",
                    "Kürzel": "Lhr",
                    "Angebote": "6a Sp-2025/2026-Angebot-example",
                    "E-Mail-Adressen der weiteren Schulen": "lena.lehrer@example.org",
                    "Rolle": "Lehrkraft",
                    "Interne ID": "tea-1",
                    "Export ID": "exp-tea-1",
                },
                {
                    "Nachname": "Ohnekurs",
                    "Vorname": "Oskar",
                    "Kürzel": "Ohk",
                    "Angebote": "8a Sp-2024/2025-Angebot-example",
                    "E-Mail-Adressen der weiteren Schulen": "oskar.ohnekurs@example.org",
                    "Rolle": "Lehrkraft",
                    "Interne ID": "tea-2",
                    "Export ID": "exp-tea-2",
                },
            ]
        ),
        encoding="utf-8",
    )

    config.input_mode = "monolith"
    config.target_school_year = "2025/2026"

    result = generate(config, [], [], existing_staff=[], input_mode="monolith", monolith_paths=[monolith])

    teacher_names = {(row["first_name"], row["last_name"]) for row in result.staff}
    assert teacher_names == {("Lena", "Lehrer"), ("Oskar", "Ohnekurs")}

    # Class/Roster generation still only uses current-year sections.
    assert len(result.classes) == 1
    assert len(result.rosters) == 1


def test_generate_monolith_alias_uses_canonical_email_for_renamed_teacher(tmp_path, config):
    monolith = tmp_path / "mono-alias-email.csv"
    monolith.write_text(
        make_monolith_csv(
            [
                {
                    "Nachname": "Muster",
                    "Vorname": "Max",
                    "Klassennamen": "8c",
                    "Angebote": "8c Ma-2025/2026-Angebot-example",
                    "Rolle": "Lernende",
                    "Interne ID": "stu-9",
                    "Export ID": "exp-stu-9",
                },
                {
                    "Nachname": "Probe",
                    "Vorname": "Clara Cecile",
                    "Kürzel": "Pro",
                    "Angebote": "8c Ma-2025/2026-Angebot-example",
                    "E-Mail-Adressen der weiteren Schulen": "clara.probe@example.org",
                    "Rolle": "Lehrkraft",
                    "Interne ID": "tea-9",
                    "Export ID": "exp-tea-9",
                },
            ]
        ),
        encoding="utf-8",
    )

    config.input_mode = "monolith"
    config.target_school_year = "2025/2026"

    result = generate(config, [], [], existing_staff=[], input_mode="monolith", monolith_paths=[monolith])

    by_name = {(row["first_name"], row["last_name"]): row for row in result.staff}
    assert ("Marie", "Probe") in by_name
    assert by_name[("Marie", "Probe")]["email_address"] == "marie.probe@example.org"


def test_build_teacher_records_preserves_existing_email_address(tmp_path):
    """Ensure existing staff email addresses are preserved, not regenerated.

    Bug fix: The script was regenerating email addresses during each run,
    which created duplicate teachers with modified emails (e.g., adding "1")
    when the same teacher appeared in both existing staff and export sections.
    This deactivated the original teacher and orphaned their classes.

    Solution: Preserve the email_address from existing_staff.csv when loading,
    and only generate emails for new teachers found in export sections.
    """
    aliases_file = tmp_path / "aliases.json"
    subjects_file = tmp_path / "subjects.json"
    aliases_file.write_text("[]", encoding="utf-8")
    subjects_file.write_text("{}", encoding="utf-8")
    config = GeneratorConfig(
        location_id="loc-001",
        email_domain="example.org",
        aliases_path=str(aliases_file),
        subjects_path=str(subjects_file),
    )

    # Existing staff with established email
    existing_staff = [
        {
            "person_id": "john.smith",
            "person_number": "JS",
            "first_name": "John",
            "last_name": "Smith",
            "email_address": "john.smith@example.org",  # Must be preserved
            "sis_username": "",
            "location_id": "loc-001",
        }
    ]

    # Export section references the same teacher
    sections = [
        {
            "teacher_first": "John",
            "teacher_last": "Smith",
            "teacher_abbr": "JS",
            "rows": [],
        }
    ]

    result = build_teacher_records(sections, existing_staff, config)

    # Should produce exactly one teacher record (no duplicate)
    assert len(result) == 1

    teacher = result[("John", "Smith")]
    # Email must be the original one, not regenerated
    assert teacher["email_address"] == "john.smith@example.org"
    assert "1@" not in teacher["email_address"]  # No collision suffix
