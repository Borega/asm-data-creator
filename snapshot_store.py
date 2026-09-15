"""Snapshot store for ASM Generator.

Persists GeneratorResult as JSON to the user's application data directory.

Storage path (Windows):
  C:\\Users\\<user>\\AppData\\Local\\ASMGenerator\\snapshot.json

Call save_snapshot() only after the ZIP export is successfully written (Phase 3
wires the timing). This module provides the read/write primitives only.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone

from asm_generator.config import GeneratorResult
from settings_store import _DATA_DIR

SNAPSHOT_DIR  = _DATA_DIR
SNAPSHOT_PATH = SNAPSHOT_DIR / "snapshot.json"


def load_snapshot() -> GeneratorResult | None:
    """Load the last saved GeneratorResult from disk.

    Returns None if no snapshot exists (first run).
    Raises json.JSONDecodeError if the file exists but is corrupted.
    """
    try:
        with open(SNAPSHOT_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    # json.JSONDecodeError is intentionally NOT caught — corrupted snapshot
    # should surface to the caller (GUI will display an error dialog).
    return GeneratorResult(
        students=data["students"],
        staff=data["staff"],
        courses=data["courses"],
        classes=data["classes"],
        rosters=data["rosters"],
        warnings=data.get("warnings", []),
    )


def load_provenance() -> dict:
    """How the snapshot was produced: ``{"saved_at": iso, "via": "upload"|"export"}``.

    Empty when the file is missing, unreadable, or was written before provenance
    existed. Empty means *unknown*, never *safe*: a snapshot of unknown origin
    may predate a change in how ids are built, in which case its ADDED/DELETED
    labels describe the file, not ASM — so holding a row back can deactivate a
    live account, and keeping one can create a duplicate.
    """
    try:
        with open(SNAPSHOT_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    prov = data.get("provenance")
    return prov if isinstance(prov, dict) else {}


def save_snapshot(result: GeneratorResult, *, via: str = "export", staff_id_source: str = "") -> None:
    """Atomically write GeneratorResult to snapshot.json.

    ``via`` records what the snapshot is evidence of. Only ``"upload"`` means
    ASM was actually handed these rows; ``"export"`` produced a ZIP that may
    never have been sent. ``staff_id_source`` records how the staff ids were
    built, so a later switch can be detected directly; absent in older files.

    Atomic strategy: write to a temp file on the SAME volume, then os.replace().
    The temp file dir MUST be SNAPSHOT_DIR (not tempfile.gettempdir()) to ensure
    os.replace() is an intra-volume rename (atomic on Windows via MoveFileExW).

    Raises OSError if the directory cannot be created or file cannot be written.
    Orphaned temp files are cleaned up on any write error.
    """
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)

    data = {
        "students": result.students,
        "staff":    result.staff,
        "courses":  result.courses,
        "classes":  result.classes,
        "rosters":  result.rosters,
        "warnings": result.warnings,
        "provenance": {
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "via": via,
            **({"staff_id_source": staff_id_source} if staff_id_source else {}),
        },
    }

    fd, tmp_path = tempfile.mkstemp(dir=SNAPSHOT_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, SNAPSHOT_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)   # T-02-04: clean up orphaned temp file
        except OSError:
            pass
        raise
