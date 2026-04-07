import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from asm_generator.config import GeneratorResult
import snapshot_store


def _make_result(**kwargs) -> GeneratorResult:
    defaults = dict(students=[], staff=[], courses=[], classes=[], rosters=[], warnings=[])
    defaults.update(kwargs)
    return GeneratorResult(**defaults)


@pytest.fixture
def tmp_snapshot_path(tmp_path):
    """Patch SNAPSHOT_PATH and SNAPSHOT_DIR to a temp directory."""
    snap_path = tmp_path / "snapshot.json"
    with (
        patch.object(snapshot_store, "SNAPSHOT_PATH", snap_path),
        patch.object(snapshot_store, "SNAPSHOT_DIR", tmp_path),
    ):
        yield snap_path


class TestLoadSnapshot:
    def test_returns_none_when_file_missing(self, tmp_snapshot_path):
        result = snapshot_store.load_snapshot()
        assert result is None

    def test_raises_on_invalid_json(self, tmp_snapshot_path):
        tmp_snapshot_path.write_text("NOT VALID JSON", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            snapshot_store.load_snapshot()


class TestSaveSnapshot:
    def test_round_trip_preserves_all_fields(self, tmp_snapshot_path, tmp_path):
        original = _make_result(
            students=[{"person_id": "s1", "first_name": "Anna", "last_name": "Müller"}],
            staff=[{"person_id": "t1", "first_name": "Karl", "last_name": "Braun"}],
            courses=[{"course_id": "c1", "course_name": "Mathematik"}],
            classes=[{"class_id": "cl1", "course_id": "c1", "instructor_id": "t1"}],
            rosters=[{"roster_id": "roster-cl1-s1", "class_id": "cl1", "student_id": "s1"}],
            warnings=["test warning"],
        )
        with (
            patch.object(snapshot_store, "SNAPSHOT_PATH", tmp_snapshot_path),
            patch.object(snapshot_store, "SNAPSHOT_DIR", tmp_path),
        ):
            snapshot_store.save_snapshot(original)
            loaded = snapshot_store.load_snapshot()

        assert loaded is not None
        assert loaded.students == original.students
        assert loaded.staff == original.staff
        assert loaded.courses == original.courses
        assert loaded.classes == original.classes
        assert loaded.rosters == original.rosters
        assert loaded.warnings == original.warnings

    def test_no_tmp_files_after_successful_save(self, tmp_snapshot_path, tmp_path):
        with (
            patch.object(snapshot_store, "SNAPSHOT_PATH", tmp_snapshot_path),
            patch.object(snapshot_store, "SNAPSHOT_DIR", tmp_path),
        ):
            snapshot_store.save_snapshot(_make_result())
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Orphaned .tmp files found: {tmp_files}"

    def test_creates_directory_if_not_exists(self, tmp_path):
        new_dir = tmp_path / "nested" / "data"
        snap_path = new_dir / "snapshot.json"
        with (
            patch.object(snapshot_store, "SNAPSHOT_PATH", snap_path),
            patch.object(snapshot_store, "SNAPSHOT_DIR", new_dir),
        ):
            snapshot_store.save_snapshot(_make_result())
        assert snap_path.exists()
