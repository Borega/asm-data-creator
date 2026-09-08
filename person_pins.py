"""Pins a Schuldock person UUID to the ASM person_id that must never change.

ASM keys people on ``person_id``. Change it and ASM deactivates the old account
and creates a new one — so a change in how an id is derived (a new name
spelling, a code change) replaces every affected account. Teacher accounts are
in use and cannot be recreated, so the exported id has to stay put even when
the name changes.

Schuldock's ``Interne ID`` does stay put across exports, including through name
changes. So it is the lookup key, never the exported value.

Stored beside settings.json in the user's data directory — this is per-machine
state that must survive a reinstall, so it must not live in the app bundle.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from settings_store import _DATA_DIR

_PINS_PATH = _DATA_DIR / "person_ids.json"


def load(path: str | Path | None = None) -> dict[str, str]:
    """Return the ``{uuid: person_id}`` map; empty when absent or unreadable.

    An empty map means "derive ids exactly as before", so a missing file is
    never an error.
    """
    target = Path(path) if path else _PINS_PATH
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    pins = {
        str(uid).strip(): str(pid).strip()
        for uid, pid in data.items()
        if str(uid).strip() and str(pid).strip()
    }

    # Two people pinned to one ASM account would merge them — the one outcome
    # that cannot be undone. An ambiguous pin is dropped so the id falls back to
    # being derived from the name, which is how it behaved before pinning.
    claimed: dict[str, int] = {}
    for pid in pins.values():
        claimed[pid] = claimed.get(pid, 0) + 1
    return {uid: pid for uid, pid in pins.items() if claimed[pid] == 1}


def seed_from_known_ids(
    parsed_teachers: list,
    known_person_ids: set,
    derive_person_id,
) -> tuple[dict[str, str], list[dict]]:
    """Build pins for teachers ASM already knows, and list the rest.

    ``parsed_teachers`` are ``parse_monolith()['teachers']`` rows,
    ``known_person_ids`` the ids ASM currently holds (from a snapshot or an
    activity log), ``derive_person_id(row) -> str`` the id today's code would
    generate for a row.

    A teacher whose derived id is already an ASM account is pinned outright —
    nothing changes for them, the pin just freezes it. Anyone else is returned
    as an unresolved candidate, because linking a renamed teacher to an existing
    account is a judgement call and a wrong link merges two people.
    """
    pins: dict[str, str] = {}
    unresolved: list[dict] = []

    for row in parsed_teachers:
        uid = (row.get("_uid", "") or "").strip()
        derived = derive_person_id(row)
        if not uid or not derived:
            continue
        if derived in known_person_ids:
            pins[uid] = derived
        else:
            unresolved.append({
                "uid": uid,
                "derived_person_id": derived,
                "first_name": row.get("first_name", ""),
                "last_name": row.get("last_name", ""),
                "person_number": row.get("person_number", ""),
            })

    return pins, unresolved


def remember(
    staff_uids: dict[str, str],
    exported_person_ids: set,
    path: str | Path | None = None,
) -> list[str]:
    """Pin whatever was just exported, so a new hire is protected from run two.

    Seeding fixed the backlog; without this the map never grows and every new
    teacher is exposed to a rename until someone re-seeds by hand. Called after
    a successful export, when ASM is about to hold exactly these ids.

    Only ids that actually reached the file are pinned — a staff row the user
    deselected in the review never reaches ASM, so pinning it would invent an
    account. Existing pins are never overwritten: the stored pin is the record
    of what ASM holds, and today's export already agrees with it. A pid another
    uid has claimed is skipped rather than merging two people (see load()).

    Returns the uids added.
    """
    pins = load(path)
    claimed = set(pins.values())
    added = []
    for uid, pid in staff_uids.items():
        # uid == pid means the school keys staff on the SIS uuid, where the id
        # already cannot move and a pin is meaningless. Storing it would be
        # harmless until someone switched back to name-derived ids, at which
        # point these pins would resurrect the uuids as person_ids.
        if uid == pid:
            continue
        if uid in pins or pid not in exported_person_ids or pid in claimed:
            continue
        pins[uid] = pid
        claimed.add(pid)
        added.append(uid)
    if added:
        save(pins, path)
    return added


def save(pins: dict[str, str], path: str | Path | None = None) -> None:
    """Atomically write the pin map (tempfile + os.replace, same as settings)."""
    target = Path(path) if path else _PINS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict(sorted(pins.items())), f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
