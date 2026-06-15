"""Pure transform functions — no file I/O, no global state.

All inputs are passed as arguments. UMLAUT_MAP is the only module-level constant
(pure data, not configurable).
"""
from __future__ import annotations

import hashlib
import re
from collections import OrderedDict, defaultdict

from .config import GeneratorConfig

# ---------------------------------------------------------------------------
# Module-level pure data constant (not config — never loaded from JSON)
# ---------------------------------------------------------------------------

UMLAUT_MAP = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
    "á": "a", "à": "a", "â": "a", "ã": "a",
    "é": "e", "è": "e", "ê": "e", "ë": "e",
    "í": "i", "ì": "i", "î": "i", "ï": "i",
    "ó": "o", "ò": "o", "ô": "o", "õ": "o",
    "ú": "u", "ù": "u", "û": "u",
    "ñ": "n", "ć": "c", "č": "c", "ž": "z", "š": "s",
    "ý": "y", "đ": "d", "ł": "l", "ø": "o", "ę": "e",
    "ą": "a", "ś": "s", "ź": "z",
})

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def clean_name_part(s: str) -> str:
    """Transliterate umlauts then remove any character not in [a-z0-9-]."""
    s = s.translate(UMLAUT_MAP).lower()
    s = re.sub(r"[^a-z0-9-]", "", s)
    return s


def make_person_id_parts(first_name: str, last_name: str) -> tuple:
    """Return (first_part, last_part) suitable for firstname.lastname IDs."""
    first_token = first_name.strip().split()[0] if first_name.strip() else ""
    first_part = clean_name_part(first_token)
    last_part = clean_name_part(last_name.replace(" ", ""))
    return first_part, last_part


def _make_email(first_name: str, last_name: str, domain: str) -> str:
    """Build a firstname.lastname@<domain> email for the configured domain.

    Returns an empty string when no email domain is configured.
    """
    if not domain:
        return ""
    fp, lp = make_person_id_parts(first_name, last_name)
    if fp and lp:
        local = f"{fp}.{lp}"
    elif fp:
        local = f"{fp}.unknown"
    elif lp:
        local = f"unknown.{lp}"
    else:
        local = "unknown.unknown"
    return f"{local}@{domain}"


def _validate_email(email: str, domain: str) -> str | None:
    """Validate email address against the configured domain.

    Rules:
    - Must end in @<domain> (only the configured domain is accepted)
    - Return the email if valid, None if invalid, missing, or no domain configured
    """
    if not email or not domain:
        return None
    email = email.strip()
    if not email:
        return None
    if email.lower().endswith(f"@{domain.lower()}"):
        return email
    # Invalid domain: reject
    return None


def _get_email_for_staff(
    person_id: str,
    existing_email: str | None,
    first_name: str,
    last_name: str,
    domain: str,
) -> str:
    """Determine email for a staff member.

    Rules:
    1. If existing email is valid (@<domain>): use it (even if it doesn't match name)
    2. If existing email is invalid or missing: generate from person_id@<domain>

    Args:
        person_id: The derived person_id for this staff member
        existing_email: Email from prior record (if any)
        first_name: First name (for fallback generation)
        last_name: Last name (for fallback generation)
        domain: Configured email domain (empty disables email generation)

    Returns:
        Valid email address ending in @<domain>, or empty string if no domain configured.
    """
    # Validate existing email
    if existing_email:
        validated = _validate_email(existing_email, domain)
        if validated:
            return validated

    # No valid existing email: generate from person_id
    if not domain:
        return ""
    return f"{person_id}@{domain}"



def _extract_email_candidates(raw: str) -> list[str]:
    if not raw:
        return []
    # Accept comma/space separated values and ignore non-email fragments.
    return re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", raw)


def _build_canonical_email_from_source_or_name(
    source_email_raw: str,
    first_name: str,
    last_name: str,
    domain: str,
) -> str:
    """Prefer source email local-part; always emit the configured email domain.

    Returns an empty string when no email domain is configured.
    """
    if not domain:
        return ""

    candidates = _extract_email_candidates(source_email_raw)

    for candidate in candidates:
        validated = _validate_email(candidate, domain)
        if validated:
            return validated

    for candidate in candidates:
        local = candidate.split("@", 1)[0].strip().lower()
        if local:
            return f"{local}@{domain}"

    return _make_email(first_name, last_name, domain)


def _split_student_given_names(vorname: str, rufname: str) -> tuple[str, str]:
    """Return (first_name, middle_name) from monolith name fields."""
    preferred = (rufname or "").strip() or (vorname or "").strip()
    first_name = preferred.split()[0] if preferred else ""

    full_given = (vorname or "").strip()
    if not full_given:
        return first_name, ""

    parts = full_given.split()
    if len(parts) <= 1:
        return first_name, ""

    # Keep all remaining tokens as middle name; this preserves extra given-name
    # detail while first_name stays short and UI-friendly.
    return first_name, " ".join(parts[1:])



def _derive_staff_person_id(first_name: str, last_name: str, person_number: str = "") -> str:
    """Derive robust staff person_id with safe fallbacks (never returns '.')."""
    fp, lp = make_person_id_parts(first_name, last_name)
    if fp and lp:
        return f"{fp}.{lp}"
    if lp:
        return lp
    if fp:
        return fp
    pn = clean_name_part(person_number or "")
    if pn:
        return f"staff.{pn}"
    return "staff.unknown"


def _clean_teacher_first_name(value: str) -> str:
    """Remove digits/symbols from teacher first names while preserving letters."""
    s = (value or "").strip()
    if not s:
        return ""
    s = re.sub(r"[^A-Za-zÄÖÜäöüßÀ-ÖØ-öø-ÿ'\-\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_grade_level(klasse: str) -> str:
    """Extract numeric grade level from a class name like '5a', '13c', 'Fremd 11'."""
    if not klasse:
        return ""
    m = re.match(r"^(\d+)", klasse)
    if m:
        return m.group(1)
    m = re.search(r"(\d+)", klasse)
    if m:
        return m.group(1)
    return ""


def expand_angebotsname(angebotsname: str, subject_map: dict) -> str:
    """Expand subject abbreviation in Angebotsname to full German name."""
    parts = angebotsname.split(" ", 1)
    if len(parts) < 2:
        return angebotsname
    class_prefix, subject_abbr = parts[0], parts[1]
    subject_full = subject_map.get(subject_abbr, subject_abbr)
    return f"{class_prefix} {subject_full}"


def slugify(s: str) -> str:
    """Create a URL/ID-safe slug from a string."""
    s = s.translate(UMLAUT_MAP).lower()
    s = re.sub(r"[^a-z0-9]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def make_roster_id(class_id: str, student_id: str) -> str:
    """Create a stable, high-entropy roster identifier from class+student."""
    token = f"{class_id}|{student_id}".encode()
    digest = hashlib.sha1(token).hexdigest()[:16]
    return f"roster-{digest}"

# ---------------------------------------------------------------------------
# Build functions (new signatures — no file I/O)
# ---------------------------------------------------------------------------

def build_student_records(parsed_students: list, config: GeneratorConfig) -> list:
    """Build ASM student rows from parsed student master data.

    LIB-05: person_id = externKey (school-assigned stable ID).
    Eliminates the name-derived suffix-counter scheme from generate_asm.py.
    """
    result = []
    for s in parsed_students:
        extern_key = s.get("externKey", "").strip()
        fore_name = s.get("foreName", "").strip()
        long_name = s.get("longName", "").strip()
        klasse = s.get("klasse.name", "").strip()

        # LIB-05: direct assignment — stable across name changes
        person_id = extern_key

        first_name = fore_name.split()[0] if fore_name else ""
        grade = extract_grade_level(klasse)

        email = _make_email(first_name, long_name, config.email_domain)

        result.append({
            "person_id": person_id,
            "person_number": extern_key,
            "first_name": first_name,
            "middle_name": "",
            "last_name": long_name,
            "grade_level": grade,
            "email_address": email,
            "sis_username": "",
            "password_policy": "",
            "location_id": config.location_id,
        })
    return result


def build_student_records_monolith(parsed_students: list, config: GeneratorConfig) -> list:
    """Build ASM student rows from monolith student records.

    Stable identity source: Interne ID (fallback: Export ID).
    Uses additional monolith metadata where available:
      - sis_username from Anmeldekennung
      - middle_name from additional Vorname tokens
      - email local-part from source email (canonicalized to the configured domain)
    """
    result: list = []
    for s in parsed_students:
        person_id = (s.get("interne_id", "") or "").strip() or (s.get("export_id", "") or "").strip()
        if not person_id:
            continue

        first_name, middle_name = _split_student_given_names(
            s.get("vorname", ""),
            s.get("rufname", ""),
        )
        last_name = (s.get("nachname", "") or "").strip()
        grade = extract_grade_level((s.get("class_name", "") or "").strip())
        source_email = (s.get("email", "") or "").strip() or (s.get("anmeldekennung", "") or "").strip()
        email = _build_canonical_email_from_source_or_name(
            source_email, first_name, last_name, config.email_domain
        )

        result.append(
            {
                "person_id": person_id,
                "person_number": person_id,
                "first_name": first_name,
                "middle_name": middle_name,
                "last_name": last_name,
                "grade_level": grade,
                "email_address": email,
                "sis_username": (s.get("anmeldekennung", "") or "").strip(),
                "password_policy": "",
                "location_id": config.location_id,
            }
        )
    return result


def build_teacher_records(
    sections: list,
    existing_staff: list,
    config: GeneratorConfig,
    monolith_staff: list | None = None,
) -> dict:
    """Build a dict of teacher records keyed by (first_name, last_name).

    LIB-03: existing_staff is passed as a parameter (no open("staff.csv") inside).
    Resolves teacher name aliases from config.load_aliases().

    ``monolith_staff`` can seed full Lehrkraft identity rows from Schuldock inputs,
    including teachers without active course sections.
    """
    aliases = config.load_aliases()
    teachers: dict = OrderedDict()
    seen_pids: set = set()
    pid_to_key: dict[str, tuple[str, str]] = {}

    def _ingest_seed_row(row: dict) -> None:
        if (row.get("person_id", "") or "").startswith("SAMPLE-"):
            return

        first_raw = row.get("first_name", row.get("foreName", ""))
        last_raw = row.get("last_name", row.get("longName", ""))
        first_source = _clean_teacher_first_name(first_raw)
        last_source = (last_raw or "").strip()
        first, last = aliases.get((first_source, last_source), (first_source, last_source))
        first = _clean_teacher_first_name(first)
        alias_applied = (first, last) != (first_source, last_source)

        person_number = (
            row.get("person_number", row.get("name", row.get("pnr", ""))) or ""
        ).strip()
        if not first and not last and not person_number:
            return

        pid = _derive_staff_person_id(first, last, person_number)
        existing_email = (row.get("email_address", row.get("address.email", "")) or "").strip()
        if row.get("_source") == "monolith" and alias_applied:
            # Alias target is the canonical identity; derive canonical mailbox from it.
            existing_email = ""
        validated_email = _validate_email(existing_email, config.email_domain)

        if pid in seen_pids:
            existing_key = pid_to_key.get(pid)
            if existing_key:
                teachers[(first, last)] = teachers[existing_key]
                rec = teachers[existing_key]
                if person_number and not rec.get("person_number"):
                    rec["person_number"] = person_number
                if validated_email:
                    rec["email_address"] = validated_email
                if (row.get("sis_username", "") or "").strip() and not rec.get("sis_username"):
                    rec["sis_username"] = (row.get("sis_username", "") or "").strip()
            return

        canonical_pid = pid
        seen_pids.add(canonical_pid)
        key = (first, last)
        email = _get_email_for_staff(
            canonical_pid, existing_email, first, last, config.email_domain
        )
        teachers[key] = {
            "person_id": canonical_pid,
            "person_number": person_number,
            "first_name": first,
            "last_name": last,
            "email_address": email,
            "sis_username": row.get("sis_username", ""),
            "location_id": config.location_id,
        }
        pid_to_key[canonical_pid] = key

    seed_rows: list[dict] = []
    if monolith_staff:
        seed_rows.extend(monolith_staff)
    seed_rows.extend(existing_staff)

    for row in seed_rows:
        _ingest_seed_row(row)

    # Add/update from export sections
    for sec in sections:
        first = _clean_teacher_first_name(sec["teacher_first"])
        last = sec["teacher_last"]
        abbr = sec["teacher_abbr"]
        first, last = aliases.get((first, last), (first, last))
        first = _clean_teacher_first_name(first)

        # Placeholder section from missing instructor mapping: do not create phantom staff row.
        if not first and not last and not (abbr or "").strip():
            continue

        key = (first, last)
        if key not in teachers:
            pid = _derive_staff_person_id(first, last, abbr or "")
            if pid in seen_pids:
                # Collision means we treat this as the same teacher identity.
                existing_key = pid_to_key.get(pid)
                if existing_key:
                    teachers[key] = teachers[existing_key]
                    rec = teachers[key]
                    if abbr and not rec.get("person_number"):
                        rec["person_number"] = abbr
            else:
                seen_pids.add(pid)
                email = _get_email_for_staff(pid, "", first, last, config.email_domain)
                teachers[key] = {
                    "person_id": pid,
                    "person_number": abbr or "",
                    "first_name": first,
                    "last_name": last,
                    "email_address": email,
                    "sis_username": "",
                    "location_id": config.location_id,
                }
                pid_to_key[pid] = key
        else:
            rec = teachers[key]
            if abbr and not rec.get("person_number"):
                rec["person_number"] = abbr

    return teachers


def build_course_records(
    sections: list, config: GeneratorConfig
) -> dict:
    """Build a dict of course records keyed by angebotsname."""
    subjects = config.load_subjects()
    courses_map: dict = OrderedDict()
    for sec in sections:
        an = sec.get("angebotsname")
        if not an:
            continue
        if an not in courses_map:
            course_id = slugify(an)
            courses_map[an] = {
                "course_id": course_id,
                "course_number": an,
                "course_name": expand_angebotsname(an, subjects),
                "location_id": config.location_id,
            }
    return courses_map


def build_class_records(
    sections: list,
    courses_map: dict,
    teacher_records: dict,
    student_records: list,
    config: GeneratorConfig,
) -> tuple:
    """Build class and roster records.

    Returns (classes: list[dict], rosters: list[dict], warnings: list[str]).
    warnings contains messages about unmatched export student rows.
    """
    # Build student lookup: (last_name, first_name) → person_id
    student_pid_lookup: dict = {}
    for sr in student_records:
        key = (sr["last_name"].strip(), sr.get("first_name", "").strip())
        student_pid_lookup[key] = sr["person_id"]

    # Pre-load aliases for teacher name resolution inside the loop
    aliases = config.load_aliases()

    classes_by_an: dict = defaultdict(list)
    for sec in sections:
        an = sec.get("angebotsname")
        if not an:
            continue
        tf = sec["teacher_first"]
        tl = sec["teacher_last"]
        # Resolve alias before lookup so aliased teachers find their record
        tf, tl = aliases.get((tf, tl), (tf, tl))
        teacher_key = (tf, tl)
        teacher_pid = teacher_records.get(teacher_key, {}).get("person_id", "")
        classes_by_an[an].append({"teacher_pid": teacher_pid, "rows": sec["rows"]})

    classes: list = []
    rosters: list = []
    warnings: list = []

    for an, class_entries in classes_by_an.items():
        course_id = courses_map[an]["course_id"]
        teacher_pids = list(dict.fromkeys(
            e["teacher_pid"] for e in class_entries if e["teacher_pid"]
        ))
        class_id = f"cls-{slugify(an)}"
        instructor_ids = (teacher_pids + ["", "", ""])[:3]

        classes.append({
            "class_id": class_id,
            "class_number": an,
            "course_id": course_id,
            "instructor_id": instructor_ids[0],
            "instructor_id_2": instructor_ids[1],
            "instructor_id_3": instructor_ids[2],
            "location_id": config.location_id,
        })

        seen_students: set = set()
        for entry in class_entries:
            for row in entry["rows"]:
                lookup_key = (row["nachname"].strip(), row["vorname"].strip())
                pid = student_pid_lookup.get(lookup_key)
                if pid is None:
                    first_word = row["vorname"].split()[0] if row["vorname"] else ""
                    for (sln, sfn), spid in student_pid_lookup.items():
                        if sln == row["nachname"] and sfn.split()[0] == first_word:
                            pid = spid
                            break
                if pid is None:
                    warnings.append(
                        f"WARNING: unmatched student "
                        f"{row['vorname']} {row['nachname']} in {an}"
                    )
                    continue
                if pid not in seen_students:
                    seen_students.add(pid)
                    rosters.append({
                        "roster_id": make_roster_id(class_id, pid),
                        "class_id": class_id,
                        "student_id": pid,
                    })

    return classes, rosters, warnings
