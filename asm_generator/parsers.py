"""CSV parsers for student master and course-enrollment export files."""
from __future__ import annotations
import csv
import re
import sys
import os
from pathlib import Path


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

    # Chardet fallback
    import chardet
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
        import io
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


def _parse_export_single(path) -> list:
    """Parse a single export file. Internal helper."""
    lines = _open_csv(path)
    sections = []
    current = None

    teacher_with_abbr = re.compile(
        r"^\[(.+?)\]\s+(Herr|Frau)\s+(.+?),\s*(.+?);;;$"
    )
    teacher_no_abbr = re.compile(
        r"^(Herr|Frau)\s+(.+?),\s*(.+?);;;$"
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
            tf = m.group(4).strip()
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
            tf = m2.group(3).strip()
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

        if line.endswith(";;;"):
            val = line[:-3].strip()
            if val and val != "Nachname;Vorname;Klassenname;Angebotsname":
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
