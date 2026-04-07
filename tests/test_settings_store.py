"""Tests for SettingsStore — persistence, defaults, and atomic write."""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import settings_store as ss_module
from settings_store import SettingsStore


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Redirect SettingsStore's data dir and path to a temp directory."""
    fake_data_dir = tmp_path / "asm_data"
    fake_settings_path = fake_data_dir / "settings.json"
    monkeypatch.setattr(ss_module, "_DATA_DIR", fake_data_dir)
    monkeypatch.setattr(ss_module, "_SETTINGS_PATH", fake_settings_path)
    yield fake_settings_path


class TestSettingsStoreLoad:
    def test_returns_defaults_when_no_file_exists(self, isolated_settings):
        result = SettingsStore.load()
        assert result["location_id"] == ""
        assert result["email_domain"] == ""
        assert result["teacher_aliases_path"] == ""
        assert result["subject_map_path"] == ""
        assert result["last_student_paths"] == []
        assert result["last_teacher_paths"] == []
        assert result["last_export_paths"] == []

    def test_returns_defaults_on_corrupt_json(self, isolated_settings):
        settings_path = isolated_settings
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text("NOT VALID JSON", encoding="utf-8")
        result = SettingsStore.load()
        assert result["location_id"] == ""

    def test_loads_saved_values(self, isolated_settings):
        settings_path = isolated_settings
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "location_id": "R001",
            "email_domain": "test.de",
            "teacher_aliases_path": "",
            "subject_map_path": "",
            "last_student_paths": [],
            "last_teacher_paths": [],
            "last_export_paths": [],
        }
        settings_path.write_text(json.dumps(data), encoding="utf-8")

        result = SettingsStore.load()
        assert result["location_id"] == "R001"
        assert result["email_domain"] == "test.de"

    def test_merges_missing_keys_with_defaults(self, isolated_settings):
        """If settings.json has only some keys, missing ones are filled from defaults."""
        settings_path = isolated_settings
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps({"location_id": "X"}), encoding="utf-8")
        result = SettingsStore.load()
        assert result["location_id"] == "X"
        assert "email_domain" in result  # filled from defaults


class TestSettingsStoreSave:
    def test_round_trip(self, isolated_settings):
        data = {
            "location_id": "R999",
            "email_domain": "schule.de",
            "teacher_aliases_path": "/some/path.json",
            "subject_map_path": "",
            "last_student_paths": ["/a/Student.csv"],
            "last_teacher_paths": [],
            "last_export_paths": ["/a/export1.csv", "/a/export2.csv"],
        }
        SettingsStore.save(data)
        loaded = SettingsStore.load()
        assert loaded["location_id"] == "R999"
        assert loaded["email_domain"] == "schule.de"
        assert loaded["last_student_paths"] == ["/a/Student.csv"]
        assert loaded["last_export_paths"] == ["/a/export1.csv", "/a/export2.csv"]

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        """Save should create the data dir if it does not exist."""
        deep_dir = tmp_path / "nested" / "deep" / "dir"
        deep_path = deep_dir / "settings.json"
        monkeypatch.setattr(ss_module, "_DATA_DIR", deep_dir)
        monkeypatch.setattr(ss_module, "_SETTINGS_PATH", deep_path)

        SettingsStore.save({"location_id": "test"})
        assert deep_path.exists()

    def test_atomic_write_no_partial_file_on_failure(self, isolated_settings, monkeypatch):
        """If os.replace fails, no settings.json should be created."""
        def boom(src, dst):
            raise OSError("simulated failure")

        monkeypatch.setattr(ss_module.os, "replace", boom)

        settings_path = isolated_settings
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        with pytest.raises(OSError):
            SettingsStore.save({"location_id": "X"})

        # settings.json must NOT exist after the failure
        assert not settings_path.exists()

    def test_utf8_encoding_preserved(self, isolated_settings):
        """German characters round-trip without garbling."""
        data = {k: "" for k in [
            "location_id", "email_domain", "teacher_aliases_path",
            "subject_map_path",
        ]}
        data["last_student_paths"] = []
        data["last_teacher_paths"] = []
        data["last_export_paths"] = []
        data["email_domain"] = "schüler-räume.de"

        SettingsStore.save(data)
        loaded = SettingsStore.load()
        assert loaded["email_domain"] == "schüler-räume.de"
