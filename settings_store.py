"""Settings persistence for ASM Generator.

Stores settings.json in the same platformdirs directory as snapshot.json:
  %LOCALAPPDATA%\\ASMGenerator\\settings.json

This module owns the data directory; snapshot_store and person_pins import it.
"""
import json
import os
import shutil
import tempfile
from pathlib import Path

import platformdirs

_DATA_DIR = Path(platformdirs.user_data_dir("ASMGenerator", appauthor=False))
_SETTINGS_PATH = _DATA_DIR / "settings.json"
# Earlier private builds kept the same files one folder deeper, under an
# appauthor. Carried over once by _adopt_legacy_data().
_LEGACY_DIR = Path(platformdirs.user_data_dir("ASMGenerator", "SchuleRissen"))
_LEGACY_FILES = ("person_ids.json", "snapshot.json", "settings.json")  # settings last

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
    "diff_baseline_mode": "snapshot",  # snapshot | activity_log | csv
    "diff_baseline_path": "",
    "staff_diff_activity_log_path": "",  # legacy compatibility key
    # How a staff person_id is built. "interne_id" uses the SIS uuid, which never
    # moves when a name changes — the right choice, and what students already do.
    # A school with existing ASM staff accounts cannot switch to it, because the
    # id IS the account: changing it deactivates every teacher and creates them
    # again. So this default applies to a fresh install only; see load().
    "staff_id_source": "interne_id",  # interne_id | name
}


def _adopt_legacy_data() -> None:
    """Copy data from the legacy folder once, if this folder has no settings yet.

    settings.json is copied last, so an interrupted copy is retried next start.
    """
    if _SETTINGS_PATH.exists() or not (_LEGACY_DIR / "settings.json").exists():
        return
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        for name in _LEGACY_FILES:
            src, dst = _LEGACY_DIR / name, _DATA_DIR / name
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)
    except OSError:
        pass  # load() still treats this as an existing install


def _existing_install_defaults() -> dict:
    """Defaults for an install that has run before: never re-key its staff."""
    return {**_DEFAULTS, "staff_id_source": "name"}


class SettingsStore:
    @staticmethod
    def load() -> dict:
        """Return settings dict; returns defaults if file missing or corrupt."""
        _adopt_legacy_data()
        if not _SETTINGS_PATH.exists():
            # No settings, but a snapshot means an export happened — the
            # staff accounts exist already (e.g. someone reset settings).
            if (_LEGACY_DIR / "settings.json").exists() or (_DATA_DIR / "snapshot.json").exists():
                return _existing_install_defaults()
            return dict(_DEFAULTS)
        try:
            with open(_SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults so any new keys are present
            merged = dict(_DEFAULTS)
            merged.update(data)

            # An install that predates this setting has ASM accounts keyed by
            # name. Letting the "interne_id" default reach it would re-key every
            # member of staff at once — ASM deactivates all of them and creates
            # them again under new ids, which is unrecoverable for accounts in
            # use. Tested against `data`, the file as written: `merged` already
            # carries the default by this point, so checking it would be a no-op
            # that silently does the damage.
            if "staff_id_source" not in data:
                merged["staff_id_source"] = "name"

            # Migration bridge: prior versions stored only the activity-log path for
            # a staff-only baseline. Promote that setting to the new generic
            # full diff-baseline keys when no explicit baseline is configured.
            if (
                (merged.get("diff_baseline_mode", "snapshot") or "snapshot") == "snapshot"
                and not (merged.get("diff_baseline_path", "") or "").strip()
            ):
                legacy_path = (merged.get("staff_diff_activity_log_path", "") or "").strip()
                if legacy_path:
                    merged["diff_baseline_mode"] = "activity_log"
                    merged["diff_baseline_path"] = legacy_path

            return merged
        except (json.JSONDecodeError, OSError):
            # A file exists, so this is not a fresh install.
            return _existing_install_defaults()

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
