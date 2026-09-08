"""CSV parsers for student master and course-enrollment export files."""
from __future__ import annotations

import csv
import io
import os
import re
import sys

from .transform import _clean_teacher_first_name


def _open_csv(path) -> list:
    """Open a text file with utf-8-sig; fall back to chardet on UnicodeDecodeError.

    Returns file lines as a list of strings (newlines preserved).
    Raises ValueError if path is not a regular file.
    Raises ValueError if chardet confidence < 0.5 and utf-8-sig also fails.
    """
    path = str(path)
    if not os.path.isfile(path):
        raise ValueError(f"File not found or not a regular file: {path}")
    try:
        with open(path, encoding="utf-8-sig") as f:
            return f.readlines()
    except UnicodeDecodeError:
        pass

    # Chardet fallback (optional dependency).
    try:
        import chardet
    except ModuleNotFoundError:
        with open(path, encoding="cp1252") as f:
            return f.readlines()

    with open(path, "rb") as fb:
        raw = fb.read()
    detected = chardet.detect(raw)
    enc = detected.get("encoding")
    confidence = detected.get("confidence", 0.0)
    if not enc:
        raise ValueError(
            f"Cannot detect encoding for {path} "
            f"(chardet returned no result)"
        )
    # Windows-1252 / cp1252 systematically score low against UTF-8 because
    # most bytes are valid in both; use the detected encoding regardless of
    # confidence, but warn when confidence is below 0.5.
    if confidence < 0.5:
        print(
            f"[parsers] {path}: low-confidence encoding detection "
            f"({enc}, confidence={confidence:.2f}) — using detected encoding",
            file=sys.stderr,
        )
    else:
        print(f"[parsers] {path}: detected encoding {enc} (confidence={confidence:.2f})", file=sys.stderr)
    with open(path, encoding=enc) as f:
        return f.readlines()


def parse_students(paths: list) -> list:
    """Parse one or more tab-separated student master CSV files.

    Records from later files overwrite earlier records with the same externKey
    (last occurrence wins). All files must share the same column schema.

    Raises ValueError if paths is empty.
    """
    if not paths:
        raise ValueError("parse_students: paths must not be empty")

    merged: dict = {}  # externKey → record
    for path in paths:
        lines = _open_csv(path)
        text = "".join(lines)
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")
        for row in reader:
            key = row.get("externKey", "").strip()
            if key:
                merged[key] = row
            # Rows without externKey are appended (can't deduplicate these)
            # but school exports always have externKey for every student.
    return list(merged.values())


def parse_export(paths: list) -> list:
    """Parse one or more semicolon-separated course-enrollment export files.

    Sections from later files are appended after sections from earlier files.
    Each section dict: {teacher_abbr, teacher_first, teacher_last, angebotsname, rows:[]}
    Each row in rows: {nachname, vorname, klassenname, angebotsname}

    Raises ValueError if paths is empty.
    """
    if not paths:
        raise ValueError("parse_export: paths must not be empty")

    all_sections: list = []
    for path in paths:
        all_sections.extend(_parse_export_single(path))
    return all_sections


def _normalize_offer_name(token: str) -> str:
    """Normalize monolith offer tokens into stable course/class names."""
    s = (token or "").strip()
    if not s:
        return ""
    s = re.sub(r"-\d{4}/\d{4}-Angebot-\w+$", "", s)
    s = s.replace("L:G", "LG")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _preferred_student_first_name(vorname: str, rufname: str) -> str:
    """Prefer Rufname; fall back to Vorname."""
    selected = (rufname or "").strip() or (vorname or "").strip()
    return selected.split()[0] if selected else ""


def _split_offers(raw: str, target_school_year: str = "") -> list[str]:
    """Split comma-separated offers, normalize names, and optionally filter by year."""
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if target_school_year and target_school_year not in token:
            continue
        normalized = _normalize_offer_name(token)
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


def _pick(row: dict, *names: str) -> str:
    """First non-empty value among *names*.

    Schuldock renames export columns between releases (``Klassennamen`` became
    ``Klassen (aktiv)``, ``Anmeldekennung`` became ``Benutzerkennung``, …).
    Listing the current name first and the historic ones after keeps older
    exports parsable without a second code path.
    """
    for name in names:
        value = (row.get(name, "") or "").strip()
        if value:
            return value
    return ""


def _class_from_row(row: dict) -> str:
    """Extract the active main class label (e.g. '5a') from monolith fields."""
    active = _pick(row, "Klassen (aktiv)", "Klassennamen")
    if active:
        return active.split(",")[0].strip()
    raw = _pick(row, "Klassen (alle)", "Klassen")
    if not raw:
        return ""
    # Historic "Klassen" held internal group names ('5a-2025/2026-Klasse-rissen').
    return raw.split(",")[0].split("-", 1)[0].strip()


def parse_monolith(paths: list, target_school_year: str = "") -> dict:
    """Parse one or more semicolon-delimited monolith user exports.

    Returns dict with:
      - students: list[dict]
      - sections: list[dict] (legacy-compatible export sections)
      - teachers: list[dict] (all Lehrkraft identities from source rows)
      - warnings: list[str]
    """
    if not paths:
        raise ValueError("parse_monolith: paths must not be empty")

    students: list[dict] = []
    staff_rows: list[dict] = []
    warnings: list[str] = []
    pending_rows: list[dict] = []
    year_counts: dict[str, int] = {}

    for path in paths:
        lines = _open_csv(path)
        text = "".join(lines)
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        for row in reader:
            role = (row.get("Rolle", "") or "").strip()
            raw_offers = _pick(row, "Angebote")
            # Vote on the school year from the offer tokens themselves — they are
            # what gets filtered, and every enrolled person carries them.
            for m in re.finditer(r"(\d{4}/\d{4})", raw_offers):
                year_counts[m.group(1)] = year_counts.get(m.group(1), 0) + 1
            item = {
                "nachname": (row.get("Nachname", "") or "").strip(),
                "vorname": (row.get("Vorname", "") or "").strip(),
                "rufname": (row.get("Rufname", "") or "").strip(),
                "email": _pick(row, "Weitere E-Mail-Adressen", "E-Mail-Adressen der weiteren Schulen"),
                "anmeldekennung": _pick(row, "Benutzerkennung", "Anmeldekennung"),
                "status": (row.get("Status", "") or "").strip(),
                "quelle": (row.get("Quelle", "") or "").strip(),
                "abbr": (row.get("Kürzel", "") or "").strip(),
                "class_name": _class_from_row(row),
                "jahrgangsstufe": _pick(row, "Jahrgangsstufe"),
                "interne_id": (row.get("Interne ID", "") or "").strip(),
                "export_id": (row.get("Export ID", "") or "").strip(),
                "raw_offers": raw_offers,
                "role": role,
            }
            pending_rows.append(item)

    effective_year = target_school_year.strip()
    if not effective_year and year_counts:
        effective_year = max(year_counts.items(), key=lambda kv: kv[1])[0]

    for item in pending_rows:
        item["offers"] = _split_offers(item.get("raw_offers", ""), effective_year)
        item.pop("raw_offers", None)
        if item["role"] == "Lernende":
            students.append(item)
        elif item["role"] == "Lehrkraft":
            staff_rows.append(item)

    # Schema-drift guard: a renamed column reads as empty for every row rather
    # than raising, which is how four fields went silently blank at once.
    # Only the class label is guarded — losing 'Jahrgangsstufe' alone still
    # leaves the class-name fallback, which is what older exports always used.
    if students and not any(s["class_name"] for s in students):
        warnings.append(
            "WARNING: no student class names found — the export is missing the "
            "'Klassen (aktiv)' column (renamed?); grade levels will be blank."
        )

    staff_by_offer: dict[str, list[dict]] = {}
    for person in staff_rows:
        for offer in person["offers"]:
            staff_by_offer.setdefault(offer, []).append(person)

    students_by_offer: dict[str, list[dict]] = {}
    for person in students:
        for offer in person["offers"]:
            students_by_offer.setdefault(offer, []).append(person)

    sections: list[dict] = []
    for offer in sorted(students_by_offer.keys()):
        teachers = staff_by_offer.get(offer, [])
        if not teachers:
            warnings.append(f"WARNING: no instructor mapping for offer {offer}")
            teachers = [{"vorname": "", "nachname": "", "abbr": ""}]

        rows = [
            {
                "nachname": s["nachname"],
                "vorname": _preferred_student_first_name(
                    s.get("vorname", ""),
                    s.get("rufname", ""),
                ),
                "klassenname": s["class_name"],
                "angebotsname": offer,
            }
            for s in students_by_offer[offer]
        ]

        for teacher in teachers:
            sections.append(
                {
                    "teacher_abbr": teacher.get("abbr", ""),
                    "teacher_first": _clean_teacher_first_name(teacher.get("vorname", "")),
                    "teacher_last": teacher.get("nachname", ""),
                    "angebotsname": offer,
                    "rows": rows,
                }
            )

    teacher_rows_by_key: dict[tuple[str, str, str], dict] = {}
    for person in staff_rows:
        first_name = _clean_teacher_first_name(person.get("vorname", ""))
        last_name = (person.get("nachname", "") or "").strip()
        person_number = (person.get("abbr", "") or "").strip()
        if not first_name and not last_name and not person_number:
            continue

        dedupe_key = (first_name, last_name, person_number)
        existing = teacher_rows_by_key.get(dedupe_key)
        if existing is None:
            teacher_rows_by_key[dedupe_key] = {
                "first_name": first_name,
                "last_name": last_name,
                "person_number": person_number,
                "email_address": (person.get("email", "") or "").strip(),
                "person_id": "",
                "sis_username": (person.get("anmeldekennung", "") or "").strip(),
                # Survives renames (verified across four exports), so it is the
                # key an ASM person_id can be pinned to.
                "_uid": (person.get("interne_id", "") or "").strip()
                or (person.get("export_id", "") or "").strip(),
                "_source": "monolith",
            }
            continue

        # Merge duplicates conservatively: keep first, fill missing fields.
        if not existing.get("email_address"):
            existing["email_address"] = (person.get("email", "") or "").strip()
        if not existing.get("sis_username"):
            existing["sis_username"] = (person.get("anmeldekennung", "") or "").strip()
        if not existing.get("_uid"):
            existing["_uid"] = (person.get("interne_id", "") or "").strip()

    teacher_rows = list(teacher_rows_by_key.values())

    return {"students": students, "sections": sections, "teachers": teacher_rows, "warnings": warnings}


def _parse_export_single(path) -> list:
    """Parse a single export file. Internal helper."""
    lines = _open_csv(path)
    sections = []
    current = None

    # Both old format (trailing ;;;) and new format (no trailing semicolons)
    teacher_with_abbr = re.compile(
        r"^\[(.+?)\]\s+(Herr|Frau)\s+(.+?),\s*(.+?)(?:;;;)?$"
    )
    teacher_no_abbr = re.compile(
        r"^(Herr|Frau)\s+(.+?),\s*(.+?)(?:;;;)?$"
    )

    i = 0
    while i < len(lines):
        raw = lines[i].rstrip("\n")
        line = raw.strip()
        i += 1

        if not line:
            continue

        m = teacher_with_abbr.match(line)
        if m:
            if current:
                sections.append(current)
            tf = _clean_teacher_first_name(m.group(4).strip())
            tl = m.group(3).strip()
            # NOTE: alias resolution is deferred to transform.py (config needed)
            current = {
                "teacher_abbr": m.group(1).strip(),
                "teacher_first": tf,
                "teacher_last": tl,
                "angebotsname": None,
                "rows": [],
            }
            continue

        m2 = teacher_no_abbr.match(line)
        if m2:
            if current:
                sections.append(current)
            tf = _clean_teacher_first_name(m2.group(3).strip())
            tl = m2.group(2).strip()
            current = {
                "teacher_abbr": None,
                "teacher_first": tf,
                "teacher_last": tl,
                "angebotsname": None,
                "rows": [],
            }
            continue

        if current is None:
            continue

        # Angebotsname lines end with one or more semicolons (old: ;;;, new: ;;;;)
        if line.endswith(";"):
            val = line.rstrip(";").strip()
            if val and val != "Nachname" and ";" not in val:
                current["angebotsname"] = val
            continue

        if line == "Nachname;Vorname;Klassenname;Angebotsname":
            continue

        if line == ";;;":
            continue

        if current["angebotsname"] and ";" in line:
            parts = [p.strip() for p in line.split(";")]
            if len(parts) >= 2 and parts[0]:
                current["rows"].append({
                    "nachname": parts[0],
                    "vorname": parts[1],
                    "klassenname": parts[2] if len(parts) > 2 else "",
                    "angebotsname": parts[3] if len(parts) > 3 else current["angebotsname"],
                })

    if current:
        sections.append(current)

    return sections
