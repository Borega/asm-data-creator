"""Settings persistence for ASM Generator.

Stores settings.json in the same platformdirs directory as snapshot.json:
  %LOCALAPPDATA%\\SchuleRissen\\ASMGenerator\\settings.json
"""
import json
import os
import tempfile
from pathlib import Path

import platformdirs

_DATA_DIR = Path(platformdirs.user_data_dir("ASMGenerator", "SchuleRissen"))
_SETTINGS_PATH = _DATA_DIR / "settings.json"

_DEFAULTS: dict = {
    "location_id": "",
    "email_domain": "",
    "teacher_aliases_path": "",
    "subject_map_path": "",
    "sftp_username": "",
    "input_mode": "schuldock",
    "target_school_year": "",
    "last_student_paths": [],
    "last_teacher_paths": [],
    "last_export_paths": [],
    "last_monolith_paths": [],
}


class SettingsStore:
    @staticmethod
    def load() -> dict:
        """Return settings dict; returns defaults if file missing or corrupt."""
        if not _SETTINGS_PATH.exists():
            return dict(_DEFAULTS)
        try:
            with open(_SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults so any new keys are present
            merged = dict(_DEFAULTS)
            merged.update(data)
            return merged
        except (json.JSONDecodeError, OSError):
            return dict(_DEFAULTS)

    @staticmethod
    def save(data: dict) -> None:
        """Atomically write settings to disk via tempfile + os.replace."""
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=_DATA_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())   # ensure data reaches disk before rename
            os.replace(tmp_path, _SETTINGS_PATH)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
