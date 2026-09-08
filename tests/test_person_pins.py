"""Identity pinning — keeping a teacher on the ASM account they already have."""

from __future__ import annotations

import json

import person_pins
from asm_generator.config import GeneratorConfig
from asm_generator.transform import build_teacher_records


def _config(tmp_path, aliases="[]") -> GeneratorConfig:
    a = tmp_path / "aliases.json"
    a.write_text(aliases, encoding="utf-8")
    s = tmp_path / "subjects.json"
    s.write_text("{}", encoding="utf-8")
    return GeneratorConfig(
        location_id="loc", email_domain="rissen.hamburg.de",
        aliases_path=str(a), subjects_path=str(s),
    )


def _teacher(uid: str, first: str, last: str, pnr: str = "Abc") -> dict:
    return {
        "first_name": first, "last_name": last, "person_number": pnr,
        "email_address": "", "person_id": "", "sis_username": "",
        "_uid": uid, "_source": "monolith",
    }


def test_pin_keeps_the_existing_id_when_the_name_changes(tmp_path):
    """The whole point: ASM deactivates an account whose person_id moves."""
    config = _config(tmp_path)
    uid = "65c1f2b8-2977-4545-9c19-ef78a81d81e5"

    before = build_teacher_records(
        [], [], config, monolith_staff=[_teacher(uid, "Jonte", "Falkenried", "Gr")])
    assert next(iter(before.values()))["person_id"] == "jonte.falkenried"

    # Schuldock now exports the full given name — without a pin this re-keys.
    renamed = [_teacher(uid, "Jonte-Hinrich Ole Mika", "Falkenried", "Gr")]
    unpinned = build_teacher_records([], [], config, monolith_staff=renamed)
    assert next(iter(unpinned.values()))["person_id"] == "jonte-hinrich.falkenried"

    pinned = build_teacher_records(
        [], [], config, monolith_staff=renamed, person_pins={uid: "jonte.falkenried"})
    rec = next(iter(pinned.values()))
    assert rec["person_id"] == "jonte.falkenried", "pinned id must survive the rename"
    assert rec["first_name"] == "Jonte-Hinrich", "the name itself still updates"
    assert rec["middle_name"] == "Ole Mika"


def test_no_pins_behaves_exactly_as_before(tmp_path):
    config = _config(tmp_path)
    rows = [_teacher("uid-1", "Anna", "Meier", "Mei")]
    assert (
        build_teacher_records([], [], config, monolith_staff=rows)
        == build_teacher_records([], [], config, monolith_staff=rows, person_pins={})
    )


def test_pin_for_an_unknown_uid_is_ignored(tmp_path):
    config = _config(tmp_path)
    teachers = build_teacher_records(
        [], [], config,
        monolith_staff=[_teacher("uid-1", "Anna", "Meier", "Mei")],
        person_pins={"some-other-uid": "someone.else"},
    )
    assert next(iter(teachers.values()))["person_id"] == "anna.meier"


def test_load_drops_pins_that_would_merge_two_people(tmp_path):
    """Two uids on one account is the one unrecoverable mistake — refuse both."""
    path = tmp_path / "person_ids.json"
    path.write_text(json.dumps({
        "uid-a": "shared.account",
        "uid-b": "shared.account",
        "uid-c": "own.account",
    }), encoding="utf-8")

    pins = person_pins.load(path)

    assert pins == {"uid-c": "own.account"}


def test_load_is_forgiving_about_a_missing_or_broken_file(tmp_path):
    assert person_pins.load(tmp_path / "absent.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert person_pins.load(broken) == {}
    wrong = tmp_path / "wrong.json"
    wrong.write_text('["a", "b"]', encoding="utf-8")
    assert person_pins.load(wrong) == {}


def test_save_round_trip(tmp_path):
    path = tmp_path / "person_ids.json"
    person_pins.save({"uid-1": "anna.meier", "uid-2": "bo.nordmann"}, path)
    assert person_pins.load(path) == {"uid-1": "anna.meier", "uid-2": "bo.nordmann"}
    assert not list(tmp_path.glob("*.tmp")), "atomic write must leave no temp file"


def test_seed_pins_known_accounts_and_reports_the_rest():
    rows = [
        _teacher("uid-known", "Anna", "Meier", "Mei"),
        _teacher("uid-new", "Neu", "Kollege", "Neu"),
    ]

    def derive(row):
        return f"{row['first_name'].lower()}.{row['last_name'].lower()}"

    pins, unresolved = person_pins.seed_from_known_ids(
        rows, {"anna.meier", "someone.who.left"}, derive)

    assert pins == {"uid-known": "anna.meier"}
    assert [u["derived_person_id"] for u in unresolved] == ["neu.kollege"]


def test_remember_pins_a_new_hire_after_their_first_export(tmp_path):
    """Seeding fixed the backlog; this is what stops it coming back."""
    path = tmp_path / "person_ids.json"
    person_pins.save({"uid-old": "anna.meier"}, path)

    added = person_pins.remember(
        {"uid-old": "anna.meier", "uid-new": "neu.kollege"},
        {"anna.meier", "neu.kollege"},
        path,
    )

    assert added == ["uid-new"]
    assert person_pins.load(path) == {"uid-old": "anna.meier", "uid-new": "neu.kollege"}


def test_remember_ignores_staff_that_never_reached_the_file(tmp_path):
    """A row deselected in the review never reaches ASM — pinning it invents an account."""
    path = tmp_path / "person_ids.json"

    added = person_pins.remember(
        {"uid-a": "went.out", "uid-b": "deselected.row"}, {"went.out"}, path)

    assert added == ["uid-a"]
    assert person_pins.load(path) == {"uid-a": "went.out"}


def test_remember_never_overwrites_or_double_claims(tmp_path):
    path = tmp_path / "person_ids.json"
    person_pins.save({"uid-a": "shared.account"}, path)

    added = person_pins.remember(
        {"uid-a": "moved.somewhere", "uid-b": "shared.account"},
        {"moved.somewhere", "shared.account"},
        path,
    )

    assert added == []
    assert person_pins.load(path) == {"uid-a": "shared.account"}


def test_remember_writes_nothing_when_there_is_nothing_new(tmp_path):
    path = tmp_path / "person_ids.json"
    assert person_pins.remember({"uid-a": "anna.meier"}, set(), path) == []
    assert not path.exists()


def test_generate_maps_every_uid_to_the_id_it_exported(tmp_path):
    """The map the export path pins from must agree with staff.csv."""
    from asm_generator.generator import generate

    import asm_generator.generator as gen

    config = _config(tmp_path)
    rows = [_teacher("uid-1", "Anna", "Meier", "Mei"),
            _teacher("uid-2", "Bo", "Nordmann", "Jan")]
    monkey = gen.parse_monolith
    gen.parse_monolith = lambda *a, **k: {
        "students": [], "sections": [], "teachers": rows, "warnings": []}
    try:
        result = generate(config, [], [], input_mode="schuldock")
    finally:
        gen.parse_monolith = monkey

    exported = {r["person_id"] for r in result.staff}
    assert result.staff_uids == {"uid-1": "anna.meier", "uid-2": "bo.nordmann"}
    assert set(result.staff_uids.values()) <= exported
