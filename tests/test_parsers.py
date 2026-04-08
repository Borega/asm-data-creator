"""Tests for asm_generator.parsers — LIB-01, LIB-02, LIB-06."""
import pytest
from tests.conftest import make_student_tsv, make_monolith_csv
from asm_generator.parsers import parse_students, parse_export, parse_monolith


# ---------------------------------------------------------------------------
# parse_students — basic
# ---------------------------------------------------------------------------

def test_parse_students_empty_paths_raises():
    with pytest.raises(ValueError, match="paths must not be empty"):
        parse_students([])


def test_parse_students_single_file(tmp_path):
    csv_file = tmp_path / "students.csv"
    csv_file.write_text(
        make_student_tsv([
            {"externKey": "1001", "longName": "Müller", "foreName": "Hans", "klasse.name": "5a"},
            {"externKey": "1002", "longName": "Schmidt", "foreName": "Anna", "klasse.name": "5b"},
        ]),
        encoding="utf-8",
    )
    records = parse_students([csv_file])
    assert len(records) == 2
    assert records[0]["externKey"] == "1001"
    assert records[0]["longName"] == "Müller"


# ---------------------------------------------------------------------------
# LIB-06: Encoding handling
# ---------------------------------------------------------------------------

def test_parse_students_utf8_bom(tmp_path):
    """utf-8-sig BOM is stripped; first column header is not corrupted."""
    csv_file = tmp_path / "students_bom.csv"
    # Write with BOM using utf-8-sig codec
    csv_file.write_text(
        make_student_tsv([
            {"externKey": "2001", "longName": "Öztürk", "foreName": "Leyla", "klasse.name": "7c"},
        ]),
        encoding="utf-8-sig",
    )
    records = parse_students([csv_file])
    assert len(records) == 1
    # If BOM is not stripped, externKey field name gets '\ufeffexternKey' and lookup fails
    assert records[0]["externKey"] == "2001"
    assert records[0]["longName"] == "Öztürk"


def test_parse_students_cp1252_fallback(tmp_path):
    """cp1252-encoded file is detected by chardet and decoded correctly.

    Uses a large fixture (50+ rows) so chardet has enough data for high confidence.
    """
    csv_file = tmp_path / "students_cp1252.csv"
    # Generate many rows with German characters so chardet gets high confidence
    rows = [
        {"externKey": str(3000 + i), "longName": name, "foreName": fore, "klasse.name": klass}
        for i, (name, fore, klass) in enumerate([
            ("Wäßler", "Günter", "9d"), ("Müller", "Jürgen", "8a"),
            ("Schröder", "Björn", "7b"), ("Köhler", "Käthe", "6c"),
            ("Bäcker", "Sören", "5a"), ("Grünwald", "Löwe", "10a"),
            ("Wäßler", "Günter", "9d"), ("Müller", "Jürgen", "8a"),
            ("Schröder", "Björn", "7b"), ("Köhler", "Käthe", "6c"),
            ("Bäcker", "Sören", "5a"), ("Grünwald", "Löwe", "10a"),
            ("Straßner", "Björn", "11b"), ("Kühn", "André", "12a"),
            ("Lörz", "Stéphane", "9c"), ("Großmann", "Clémence", "8b"),
            ("Häußler", "Ügür", "7a"), ("Pöttger", "Björn", "6b"),
            ("Wäßmann", "Günther", "5c"), ("Schütz", "Ödön", "10b"),
            ("Straßner", "Björn", "11b"), ("Kühn", "André", "12a"),
            ("Lörz", "Stéphane", "9c"), ("Großmann", "Clémence", "8b"),
            ("Häußler", "Ügür", "7a"), ("Pöttger", "Björn", "6b"),
        ] * 2)
    ]
    content = make_student_tsv(rows)
    csv_file.write_bytes(content.encode("cp1252"))
    records = parse_students([csv_file])
    assert len(records) > 0
    # Verify German characters are decoded correctly (not garbled)
    by_key = {r["externKey"]: r for r in records}
    assert by_key["3000"]["longName"] == "Wäßler"
    assert by_key["3000"]["foreName"] == "Günter"


# ---------------------------------------------------------------------------
# LIB-01: Multi-path merge with externKey deduplication (last wins)
# ---------------------------------------------------------------------------

def test_parse_students_multi_path_dedup_last_wins(tmp_path):
    file_a = tmp_path / "a.csv"
    file_b = tmp_path / "b.csv"

    file_a.write_text(
        make_student_tsv([
            {"externKey": "4001", "longName": "Alt", "foreName": "Max", "klasse.name": "6a"},
            {"externKey": "4002", "longName": "Braun", "foreName": "Sina", "klasse.name": "6b"},
        ]),
        encoding="utf-8",
    )
    file_b.write_text(
        make_student_tsv([
            # same externKey 4001 but updated name — should overwrite
            {"externKey": "4001", "longName": "Neu", "foreName": "Max", "klasse.name": "6a"},
        ]),
        encoding="utf-8",
    )

    records = parse_students([file_a, file_b])
    by_key = {r["externKey"]: r for r in records}

    assert len(by_key) == 2  # 4001 deduplicated, 4002 retained
    assert by_key["4001"]["longName"] == "Neu"   # last-wins
    assert by_key["4002"]["longName"] == "Braun"


# ---------------------------------------------------------------------------
# parse_export — basic
# ---------------------------------------------------------------------------

def test_parse_export_empty_paths_raises():
    with pytest.raises(ValueError, match="paths must not be empty"):
        parse_export([])


def test_parse_export_single_section(tmp_path):
    content = "[Mue] Frau Müller, Anna;;;\n5a Sp;;;\nNachname;Vorname;Klassenname;Angebotsname\nSchmidt;Hans;5a;5a Sp\n"
    export_file = tmp_path / "export.csv"
    export_file.write_text(content, encoding="utf-8")
    sections = parse_export([export_file])
    assert len(sections) == 1
    assert sections[0]["teacher_abbr"] == "Mue"
    assert sections[0]["angebotsname"] == "5a Sp"
    assert len(sections[0]["rows"]) == 1
    assert sections[0]["rows"][0]["nachname"] == "Schmidt"


def test_parse_export_cleans_teacher_first_name_symbols(tmp_path):
    content = "[Mue] Frau Müller, An(na):2;;;\n5a Sp;;;\nNachname;Vorname;Klassenname;Angebotsname\nSchmidt;Hans;5a;5a Sp\n"
    export_file = tmp_path / "export_symbols.csv"
    export_file.write_text(content, encoding="utf-8")
    sections = parse_export([export_file])
    assert sections[0]["teacher_first"] == "Anna"


# LIB-02: multi-path concatenation (sections from file2 appended after file1)
def test_parse_export_multi_path_concatenates(tmp_path):
    f1 = tmp_path / "export1.csv"
    f2 = tmp_path / "export2.csv"

    f1.write_text(
        "[Abc] Herr Schreiber, Karl;;;\n5a E;;;\nNachname;Vorname;Klassenname;Angebotsname\nMeyer;Jana;5a;5a E\n",
        encoding="utf-8",
    )
    f2.write_text(
        "[Xyz] Frau Koch, Rita;;;\n6b D;;;\nNachname;Vorname;Klassenname;Angebotsname\nKlein;Otto;6b;6b D\n",
        encoding="utf-8",
    )

    sections = parse_export([f1, f2])
    assert len(sections) == 2
    assert sections[0]["teacher_abbr"] == "Abc"
    assert sections[1]["teacher_abbr"] == "Xyz"


def test_parse_monolith_empty_paths_raises():
    with pytest.raises(ValueError, match="paths must not be empty"):
        parse_monolith([])


def test_parse_monolith_role_split_and_sections(tmp_path):
    csv_file = tmp_path / "monolith.csv"
    csv_file.write_text(
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
                    "E-Mail-Adressen der weiteren Schulen": "lena@example.org",
                    "Rolle": "Lehrkraft",
                    "Interne ID": "tea-1",
                    "Export ID": "exp-tea-1",
                },
            ]
        ),
        encoding="utf-8",
    )

    result = parse_monolith([csv_file], target_school_year="2025/2026")
    assert len(result["students"]) == 1
    assert len(result["sections"]) == 1
    assert result["sections"][0]["angebotsname"] == "6a Sp"
    assert result["sections"][0]["teacher_first"] == "Lena"
    assert result["warnings"] == []


def test_parse_monolith_year_filter_and_normalization(tmp_path):
    csv_file = tmp_path / "monolith_years.csv"
    csv_file.write_text(
        make_monolith_csv(
            [
                {
                    "Nachname": "Test",
                    "Vorname": "Tina",
                    "Klassennamen": "7b",
                    "Angebote": "##7b D-2024/2025-Angebot-rissen,7b E-2025/2026-Angebot-rissen",
                    "Rolle": "Lernende",
                    "Interne ID": "stu-2",
                    "Export ID": "exp-stu-2",
                },
            ]
        ),
        encoding="utf-8",
    )

    result = parse_monolith([csv_file], target_school_year="2025/2026")
    offers = [sec["angebotsname"] for sec in result["sections"]]
    assert offers == ["7b E"]
    assert any("no instructor mapping" in w for w in result["warnings"])


def test_parse_monolith_preserves_hash_prefixes_for_legacy_parity(tmp_path):
    csv_file = tmp_path / "monolith_hash.csv"
    csv_file.write_text(
        make_monolith_csv(
            [
                {
                    "Nachname": "Foo",
                    "Vorname": "Bar",
                    "Klassennamen": "8a",
                    "Angebote": "##FÖRDER Englisch 6-2025/2026-Angebot-rissen",
                    "Rolle": "Lernende",
                    "Interne ID": "s1",
                    "Export ID": "e1",
                }
            ]
        ),
        encoding="utf-8",
    )
    result = parse_monolith([csv_file], target_school_year="2025/2026")
    assert result["sections"][0]["angebotsname"] == "##FÖRDER Englisch 6"


def test_parse_monolith_uses_rufname_for_section_rows(tmp_path):
    csv_file = tmp_path / "monolith_rufname.csv"
    csv_file.write_text(
        make_monolith_csv(
            [
                {
                    "Nachname": "Muster",
                    "Vorname": "Maximilian",
                    "Rufname": "Max",
                    "Klassennamen": "6a",
                    "Angebote": "6a Sp-2025/2026-Angebot-rissen",
                    "Rolle": "Lernende",
                    "Interne ID": "stu-3",
                    "Export ID": "exp-stu-3",
                }
            ]
        ),
        encoding="utf-8",
    )
    result = parse_monolith([csv_file], target_school_year="2025/2026")
    assert result["sections"][0]["rows"][0]["vorname"] == "Max"
