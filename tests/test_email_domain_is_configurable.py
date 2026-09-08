"""The mail domain must come from config, so another school is not issued ours.

Every other test in the suite configures `rissen.hamburg.de`, so they would all
still pass with the domain hardcoded. These use a different one on purpose.
"""

from __future__ import annotations

import pytest

from asm_generator.config import GeneratorConfig
from asm_generator.transform import (
    build_student_records_monolith,
    build_teacher_records,
)

OTHER = "other-school.example"


def _config(tmp_path, domain: str = OTHER) -> GeneratorConfig:
    aliases = tmp_path / "aliases.json"
    aliases.write_text("[]", encoding="utf-8")
    subjects = tmp_path / "subjects.json"
    subjects.write_text("{}", encoding="utf-8")
    return GeneratorConfig(
        location_id="loc", email_domain=domain,
        aliases_path=str(aliases), subjects_path=str(subjects),
    )


def _teacher(first: str, last: str, email: str = "") -> dict:
    return {"first_name": first, "last_name": last, "person_number": "Abc",
            "email_address": email, "person_id": "", "sis_username": "",
            "_uid": "uid-1", "_source": "monolith"}


def _student(**kw) -> dict:
    base = {"interne_id": "stu-uuid-1", "vorname": "Ada", "rufname": "",
            "nachname": "Lovelace", "class_name": "10a", "jahrgangsstufe": "10",
            "email": "", "anmeldekennung": ""}
    base.update(kw)
    return base


def test_staff_emails_use_the_configured_domain(tmp_path):
    records = build_teacher_records(
        [], [], _config(tmp_path), monolith_staff=[_teacher("Anna", "Meier")])
    email = next(iter(records.values()))["email_address"]

    assert email == f"anna.meier@{OTHER}"
    assert "rissen" not in email


def test_student_emails_use_the_configured_domain(tmp_path):
    records = build_student_records_monolith([_student()], _config(tmp_path))

    assert records[0]["email_address"] == f"ada.lovelace@{OTHER}"


def test_a_source_email_keeps_its_local_part_but_takes_our_domain(tmp_path):
    """Schuldock carries addresses from elsewhere; only the local part survives."""
    records = build_student_records_monolith(
        [_student(email="ada.lovelace@someschool.example")], _config(tmp_path))

    assert records[0]["email_address"] == f"ada.lovelace@{OTHER}"


def test_an_existing_address_on_our_domain_is_kept_verbatim(tmp_path):
    """Rule 1 of _get_email_for_staff: a valid address wins even if it misfits the name."""
    records = build_teacher_records(
        [], [], _config(tmp_path),
        monolith_staff=[_teacher("Anna", "Meier", f"a.meier2@{OTHER}")])

    assert next(iter(records.values()))["email_address"] == f"a.meier2@{OTHER}"


def test_an_address_on_a_foreign_domain_is_rejected_and_rebuilt(tmp_path):
    """The old code accepted only @rissen — that check has to follow the config."""
    records = build_teacher_records(
        [], [], _config(tmp_path),
        monolith_staff=[_teacher("Anna", "Meier", "anna.meier@rissen.hamburg.de")])

    assert next(iter(records.values()))["email_address"] == f"anna.meier@{OTHER}", (
        "a rissen.hamburg.de address is foreign to this school and must not survive"
    )


def test_the_domain_is_normalised(tmp_path):
    for written in ("@" + OTHER, OTHER.upper(), f"  {OTHER}  "):
        records = build_teacher_records(
            [], [], _config(tmp_path, written), monolith_staff=[_teacher("Anna", "Meier")])
        assert next(iter(records.values()))["email_address"] == f"anna.meier@{OTHER}", written


def test_a_blank_domain_is_refused_rather_than_defaulted(tmp_path):
    """A default here would hand one school's addresses to another school."""
    with pytest.raises(ValueError, match="No email domain configured"):
        build_teacher_records(
            [], [], _config(tmp_path, ""), monolith_staff=[_teacher("Anna", "Meier")])


def test_the_error_names_the_setting_to_fix(tmp_path):
    """A fresh install hits this first; it has to say what to do."""
    with pytest.raises(ValueError) as exc:
        build_teacher_records(
            [], [], _config(tmp_path, ""), monolith_staff=[_teacher("Anna", "Meier")])

    message = str(exc.value)
    assert "Settings" in message and "Email Domain" in message
    assert "rissen" not in message.lower(), "the example must not be a real school"
