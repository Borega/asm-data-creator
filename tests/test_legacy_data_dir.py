"""Upgrading from builds that kept data under an appauthor folder.

Two separate guarantees: the data is carried over, and — even if carrying it
over fails — an install that has ever run never gets the "interne_id" default,
which would re-key every existing staff account in ASM.
"""
import json
import shutil

import pytest

import settings_store as ss


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    new, legacy = tmp_path / "new", tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "settings.json").write_text(json.dumps({"location_id": "LOC001"}), encoding="utf-8")
    (legacy / "person_ids.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ss, "_DATA_DIR", new)
    monkeypatch.setattr(ss, "_SETTINGS_PATH", new / "settings.json")
    monkeypatch.setattr(ss, "_LEGACY_DIR", legacy)
    return new, legacy


def test_legacy_data_is_carried_over_and_keeps_name_keyed_staff(dirs):
    new, _ = dirs
    settings = ss.SettingsStore.load()
    assert settings["location_id"] == "LOC001"
    assert settings["staff_id_source"] == "name"
    assert (new / "person_ids.json").exists()


def test_a_failed_copy_still_never_hands_out_interne_id(dirs, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copy2", refuse)
    assert ss.SettingsStore.load()["staff_id_source"] == "name"


def test_deleted_settings_beside_a_snapshot_is_not_a_fresh_install(dirs):
    new, legacy = dirs
    shutil.rmtree(legacy)
    new.mkdir()
    (new / "snapshot.json").write_text("{}", encoding="utf-8")
    assert ss.SettingsStore.load()["staff_id_source"] == "name"


def test_a_corrupt_settings_file_is_not_a_fresh_install(dirs):
    new, legacy = dirs
    shutil.rmtree(legacy)
    new.mkdir()
    (new / "settings.json").write_text("{not json", encoding="utf-8")
    assert ss.SettingsStore.load()["staff_id_source"] == "name"
