"""Staff keyed on the SIS uuid — right for a new school, fatal for an existing one.

ASM keys accounts on person_id. A school with no staff accounts yet should use
the SIS uuid, exactly as students already do, and then a rename can never
re-key anyone. A school whose accounts already exist under name-derived ids
cannot switch, because changing the id deactivates the account and creates a
new one — which is why the default has to be the legacy scheme.
"""

from __future__ import annotations

import json

import person_pins
from asm_generator.config import GeneratorConfig
from asm_generator.transform import build_teacher_records
from gui.app_controller import _staff_key_scheme
from settings_store import SettingsStore

UID = "65c1f2b8-2977-4545-9c19-ef78a81d81e5"


def _config(tmp_path, staff_id_source: str = "name") -> GeneratorConfig:
    aliases = tmp_path / "aliases.json"
    aliases.write_text("[]", encoding="utf-8")
    subjects = tmp_path / "subjects.json"
    subjects.write_text("{}", encoding="utf-8")
    return GeneratorConfig(
        location_id="loc", email_domain="school.example",
        aliases_path=str(aliases), subjects_path=str(subjects),
        staff_id_source=staff_id_source,
    )


def _teacher(first: str, last: str, uid: str = UID, pnr: str = "Gro") -> dict:
    return {"first_name": first, "last_name": last, "person_number": pnr,
            "email_address": "", "person_id": "", "sis_username": "",
            "_uid": uid, "_source": "monolith"}


# --------------------------------------------------------------------------
# The setting's default — the line that decides whether staff keep their ids
# --------------------------------------------------------------------------

def test_an_existing_install_without_the_key_stays_on_name_derived_ids(tmp_path, monkeypatch):
    """The 103-teacher catastrophe: a new default must not reach an old install."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"location_id": "loc"}), encoding="utf-8")
    monkeypatch.setattr("settings_store._SETTINGS_PATH", path)

    assert SettingsStore.load()["staff_id_source"] == "name"


def test_a_fresh_install_gets_the_sis_uuid_scheme(tmp_path, monkeypatch):
    monkeypatch.setattr("settings_store._SETTINGS_PATH", tmp_path / "absent.json")

    assert SettingsStore.load()["staff_id_source"] == "interne_id"


def test_an_explicit_choice_is_always_honoured(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"staff_id_source": "interne_id"}), encoding="utf-8")
    monkeypatch.setattr("settings_store._SETTINGS_PATH", path)

    assert SettingsStore.load()["staff_id_source"] == "interne_id"


def test_the_library_default_is_the_safe_one(tmp_path):
    """Constructing a config without the field must never re-key anybody."""
    config = GeneratorConfig(
        location_id="loc", email_domain="school.example",
        aliases_path=str(tmp_path / "a.json"), subjects_path=str(tmp_path / "s.json"),
    )
    assert config.staff_id_source == "name"


# --------------------------------------------------------------------------
# What each mode produces
# --------------------------------------------------------------------------

def test_uuid_mode_keys_staff_on_the_sis_id(tmp_path):
    records = build_teacher_records(
        [], [], _config(tmp_path, "interne_id"),
        monolith_staff=[_teacher("Jonte-Hinrich", "Falkenried")])

    assert next(iter(records.values()))["person_id"] == UID


def test_uuid_mode_still_gives_a_human_email_address(tmp_path):
    """The reason staff could not simply copy the student scheme."""
    email = next(iter(build_teacher_records(
        [], [], _config(tmp_path, "interne_id"),
        monolith_staff=[_teacher("Jonte-Hinrich", "Falkenried")]).values()))["email_address"]

    assert email == "jonte-hinrich.falkenried@school.example"
    assert UID not in email, "a uuid mailbox is unusable by a human"


def test_uuid_mode_keeps_the_kuerzel_as_person_number(tmp_path):
    """person_number stays the staff abbreviation; only the key changes."""
    record = next(iter(build_teacher_records(
        [], [], _config(tmp_path, "interne_id"),
        monolith_staff=[_teacher("Jonte-Hinrich", "Falkenried", pnr="Gro")]).values()))

    assert record["person_number"] == "Gro"


def test_a_rename_cannot_move_a_uuid_id(tmp_path):
    """The whole point — no pin needed, because the id was never name-derived."""
    config = _config(tmp_path, "interne_id")
    before = build_teacher_records([], [], config, monolith_staff=[_teacher("Jonte", "Falkenried")])
    after = build_teacher_records(
        [], [], config, monolith_staff=[_teacher("Jonte-Hinrich Ole Mika", "Falkenried")])

    assert next(iter(before.values()))["person_id"] == next(iter(after.values()))["person_id"]
    assert next(iter(after.values()))["first_name"] == "Jonte-Hinrich", "the name still updates"


def test_uuid_mode_ignores_pins_entirely(tmp_path):
    """A stale pin must not drag a uuid-keyed teacher back to a name-derived id."""
    records = build_teacher_records(
        [], [], _config(tmp_path, "interne_id"),
        monolith_staff=[_teacher("Jonte", "Falkenried")],
        person_pins={UID: "jonte.falkenried"})

    assert next(iter(records.values()))["person_id"] == UID


def test_name_mode_is_unchanged_and_still_honours_pins(tmp_path):
    records = build_teacher_records(
        [], [], _config(tmp_path, "name"),
        monolith_staff=[_teacher("Jonte-Hinrich", "Falkenried")],
        person_pins={UID: "jonte.falkenried"})
    record = next(iter(records.values()))

    assert record["person_id"] == "jonte.falkenried"
    assert record["email_address"] == "jonte.falkenried@school.example"


def test_a_teacher_with_no_sis_id_falls_back_to_a_name_derived_id(tmp_path):
    """Export-only teachers carry no uuid; they must still get a usable id."""
    records = build_teacher_records(
        [], [], _config(tmp_path, "interne_id"),
        monolith_staff=[_teacher("Anna", "Meier", uid="")])

    assert next(iter(records.values()))["person_id"] == "anna.meier"


def test_remember_refuses_a_pin_that_says_nothing(tmp_path):
    """In uuid mode uid == person_id; storing that would resurrect it on a switch."""
    path = tmp_path / "person_ids.json"
    assert person_pins.remember({UID: UID}, {UID}, path) == []
    assert not path.exists()


# --------------------------------------------------------------------------
# Detecting an accidental switch — the last guard before 103 deactivations
# --------------------------------------------------------------------------

def _rows(*person_ids: str) -> list[dict]:
    return [{"person_id": pid} for pid in person_ids]


def test_scheme_is_judged_by_majority_not_by_the_first_row():
    """A uuid-keyed roster still holds name-derived export-only teachers."""
    mixed = _rows(UID, "4b46aba8-a909-42d0-822d-1494e7e03c6b", "anna.meier")

    assert _staff_key_scheme(mixed) == "uuid"
    assert _staff_key_scheme(list(reversed(mixed))) == "uuid", "order must not matter"


def test_scheme_of_a_name_keyed_roster():
    assert _staff_key_scheme(_rows("anna.meier", "bo.nordmann", UID)) == "name"


def test_scheme_is_unknown_when_there_is_nothing_to_judge():
    assert _staff_key_scheme([]) == "unknown"
    assert _staff_key_scheme(_rows("", "")) == "unknown"
    assert _staff_key_scheme(_rows(UID, "anna.meier")) == "unknown", "a tie decides nothing"


def test_a_switch_is_detected_in_both_directions():
    name_keyed = _rows("anna.meier", "bo.nordmann")
    uuid_keyed = _rows(UID, "4b46aba8-a909-42d0-822d-1494e7e03c6b")

    assert _staff_key_scheme(name_keyed) != _staff_key_scheme(uuid_keyed)


def test_a_normal_run_shows_no_switch():
    """Adding and losing staff within one scheme must stay silent."""
    before = _rows("anna.meier", "bo.nordmann")
    after = _rows("anna.meier", "neu.kollege", "dritte.person")

    assert _staff_key_scheme(before) == _staff_key_scheme(after) == "name"
