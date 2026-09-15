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

def _domain(config) -> str:
    """The school's Managed Apple Account domain, normalised.

    Every school has its own, so this is configuration and never a constant.
    There is deliberately no default: a blank domain used to fall through to a
    hardcoded 'rissen.hamburg.de', which would hand one school's addresses to
    another school's students — silently, and only visible once the accounts
    exist. Refusing to generate is the lesser failure.
    """
    value = (getattr(config, "email_domain", "") or "").strip().lstrip("@").lower()
    if not value:
        raise ValueError(
            "No email domain configured. Set your school's Managed Apple Account "
            "domain (Settings → Email Domain), for example 'school.example', "
            "before generating."
        )
    return value

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


def _email_local_from_name(first_name: str, last_name: str) -> str:
    """The firstname.lastname part of an address, with fallbacks for missing halves."""
    fp, lp = make_person_id_parts(first_name, last_name)
    if fp and lp:
        return f"{fp}.{lp}"
    if fp:
        return f"{fp}.unknown"
    if lp:
        return f"unknown.{lp}"
    return "unknown.unknown"


def _make_email(first_name: str, last_name: str, domain: str) -> str:
    """Build canonical ASM email in firstname.lastname@<domain> form."""
    return f"{_email_local_from_name(first_name, last_name)}@{domain}"


def _validate_email(email: str, domain: str) -> str | None:
    """Validate email address.

    Rules:
    - Must end in @<domain> (only the school's own domain is accepted)
    - Return the email if valid, None if invalid or missing
    """
    if not email:
        return None
    email = email.strip()
    if not email:
        return None
    if email.lower().endswith(f"@{domain}"):
        return email
    # Invalid domain: reject
    return None


def _get_email_for_staff(
    email_local: str,
    existing_email: str | None,
    first_name: str,
    last_name: str,
    domain: str,
) -> str:
    """Determine email for a staff member.
    
    Rules:
    1. If existing email is on the school's domain: use it (even if it doesn't match the name)
    2. Otherwise: build one from *email_local*

    Args:
        email_local: The local part to use when generating. With name-derived
            ids this is the person_id itself, which is already firstname.lastname.
            With uuid ids it must be the name-derived local part instead — an
            address like 65c1f2b8-...@school.de is not usable by a human.
        existing_email: Email from prior record (if any)
        first_name: First name (for fallback generation)
        last_name: Last name (for fallback generation)

    Returns:
        Valid email address on *domain*
    """
    # Validate existing email
    if existing_email:
        validated = _validate_email(existing_email, domain)
        if validated:
            return validated

    # No valid existing email: generate one
    return f"{email_local}@{domain}"



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
    """Prefer source email local-part; always emit the school's own domain."""
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


def _split_given_names(first: str) -> tuple[str, str]:
    """Split 'Anna Maria Theresa' into ('Anna', 'Maria Theresa').

    Schuldock switched to exporting full given names, which otherwise land
    whole in staff.first_name. Students are already split this way; person_id
    is unaffected because it only ever used the leading token.
    """
    tokens = (first or "").split()
    if not tokens:
        return "", ""
    return tokens[0], " ".join(tokens[1:])


def resolve_staff_identity(row: dict, aliases: dict) -> tuple[str, str, str, str]:
    """Return ``(first, last, person_number, person_id)`` for a staff seed row.

    Shared by :func:`build_teacher_records` and by pin seeding so the two can
    never disagree about which id a teacher would be given — a seed that
    computed a different id than the generator would pin the wrong account.
    """
    first_source = _clean_teacher_first_name(row.get("first_name", row.get("foreName", "")))
    last_source = (row.get("last_name", row.get("longName", "")) or "").strip()
    first, last = aliases.get((first_source, last_source), (first_source, last_source))
    first = _clean_teacher_first_name(first)
    person_number = (
        row.get("person_number", row.get("name", row.get("pnr", ""))) or ""
    ).strip()
    return first, last, person_number, _derive_staff_person_id(first, last, person_number)


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


# Parallel-group and Kurs-level markers that trail a subject: '11 Phy 1',
# '12 D 2 eA', '13c E_SS 3'. They are kept in the output name so two groups of
# the same subject stay tellable apart.
_SUBJECT_VARIANT_RE = re.compile(r"^(?:\d+|[eg]A)$")

# Oberstufe suffixes: 'Bio_SS' is Biologie in the Studienstufe (years 12-13).
_SUBJECT_STAGE_SUFFIXES = {"_SS": "Studienstufe"}


def _split_subject_variants(subject: str) -> tuple[str, str]:
    """Split 'Phy 1' into ('Phy', '1'), leaving unrecognised tails on the base."""
    tokens = subject.split()
    tail: list[str] = []
    while len(tokens) > 1 and _SUBJECT_VARIANT_RE.match(tokens[-1]):
        tail.insert(0, tokens.pop())
    return " ".join(tokens), " ".join(tail)


def _lookup_subject(base: str, lookup: dict) -> str | None:
    """Resolve a subject token to its full name, or None if unrecognised.

    *lookup* is a case-folded subject map (see :func:`expand_angebotsname`);
    the source spells the same token both ways ('WP1 Spa' / 'Wp1 Spa').

    Handles three shapes beyond a plain hit:
      'Bio_SS'         -> underscore stage suffix ('Biologie Studienstufe')
      'Mu_5-10'        -> unknown suffix kept verbatim ('Musik 5-10')
      'L:AB Holz Wolke' -> longest known leading subject, remainder kept
    """
    hit = lookup.get(base.lower())
    if hit is not None:
        return hit

    if "_" in base:
        stem, _, suffix = base.rpartition("_")
        stem_full = _lookup_subject(stem, lookup) if stem else None
        if stem_full:
            stage = _SUBJECT_STAGE_SUFFIXES.get("_" + suffix.upper(), suffix)
            return f"{stem_full} {stage}"

    tokens = base.split()
    for cut in range(len(tokens) - 1, 0, -1):
        head = lookup.get(" ".join(tokens[:cut]).lower())
        if head is not None:
            return f"{head} {' '.join(tokens[cut:])}"

    return None


def expand_angebotsname(angebotsname: str, subject_map: dict) -> str:
    """Expand subject abbreviation in Angebotsname to full German name.

    Unknown subjects are returned untouched rather than guessed at.
    """
    # Leading '#'/'##'/'###' is Schuldock decoration on the offer name, not part
    # of the class. Only the display name loses it — course_number and the
    # course_id derived from it keep the original string, so identity is stable.
    display_name = angebotsname.lstrip("#").strip()
    if not display_name:
        return angebotsname

    parts = display_name.split(" ", 1)
    if len(parts) < 2:
        return display_name
    class_prefix, subject_abbr = parts[0], parts[1]

    lookup = {key.lower(): value for key, value in subject_map.items()}

    base, variant = _split_subject_variants(subject_abbr)
    subject_full = _lookup_subject(base, lookup)
    if subject_full is not None:
        return " ".join(p for p in (class_prefix, subject_full, variant) if p)

    # Some offers carry no grade and lead with the subject instead, trailing a
    # teacher and half-year: 'Holz Wolke HJ1', 'Spo1 Badminton'. Numeric class
    # prefixes never resolve, so a real '<class> <subject>' cannot land here.
    prefix_full = _lookup_subject(class_prefix, lookup)
    if prefix_full is not None:
        return f"{prefix_full} {subject_abbr}"

    return display_name


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
    Eliminates the name-derived suffix-counter scheme the original script used.
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

        email = _make_email(first_name, long_name, _domain(config))

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
      - email local-part from source email (canonicalized to rissen domain)
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
        # Jahrgangsstufe is the authoritative grade when it is a plain number;
        # non-numeric values ('1Hj') and blanks fall back to the class label,
        # which still yields a grade for names like 'Fremd 12'.
        jahrgang = (s.get("jahrgangsstufe", "") or "").strip()
        class_name = (s.get("class_name", "") or "").strip()
        grade = jahrgang if jahrgang.isdigit() else extract_grade_level(class_name)
        source_email = (s.get("email", "") or "").strip() or (s.get("anmeldekennung", "") or "").strip()
        email = _build_canonical_email_from_source_or_name(
            source_email, first_name, last_name, _domain(config))

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
    person_pins: dict | None = None,
) -> dict:
    """Build a dict of teacher records keyed by (first_name, last_name).

    LIB-03: existing_staff is passed as a parameter (no open("staff.csv") inside).
    Resolves teacher name aliases from config.load_aliases().

    ``monolith_staff`` can seed full Lehrkraft identity rows from Schuldock inputs,
    including teachers without active course sections.
    """
    aliases = config.load_aliases()
    domain = _domain(config)
    # A school with no ASM staff accounts yet should key them on the SIS uuid, as
    # students already are — then a rename can never re-key anyone and the whole
    # pin mechanism is unnecessary. A school whose accounts already exist under
    # name-derived ids cannot switch: the id IS the account.
    use_uuid_ids = (getattr(config, "staff_id_source", "name") or "name") == "interne_id"
    pins = person_pins or {}
    teachers: dict = OrderedDict()
    seen_pids: set = set()
    pid_to_key: dict[str, tuple[str, str]] = {}

    def _ingest_seed_row(row: dict) -> None:
        if (row.get("person_id", "") or "").startswith("SAMPLE-"):
            return

        first_source = _clean_teacher_first_name(
            row.get("first_name", row.get("foreName", ""))
        )
        last_source = (row.get("last_name", row.get("longName", "")) or "").strip()
        first, last, person_number, derived_pid = resolve_staff_identity(row, aliases)
        alias_applied = (first, last) != (first_source, last_source)

        if not first and not last and not person_number:
            return

        # A pinned id is the account ASM already has; the name must not move it.
        uid = (row.get("_uid", "") or "").strip()
        if use_uuid_ids and uid:
            # The SIS uuid never moves when a name changes, so no pin is needed
            # or consulted — pinning exists only to hold a name-derived id still.
            pid = uid
        else:
            pid = pins.get(uid) or derived_pid
        existing_email = (row.get("email_address", row.get("address.email", "")) or "").strip()
        if row.get("_source") == "monolith" and alias_applied:
            # Alias target is the canonical identity; derive canonical mailbox from it.
            existing_email = ""
        validated_email = _validate_email(existing_email, domain)

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
        # The dict key keeps the full given name — that is what alias lookup
        # and section matching use. Only the exported fields are split.
        key = (first, last)
        given, middle = _split_given_names(first)
        # With name-derived ids the id already reads firstname.lastname, so it is
        # the local part. With uuid ids it must not be — nobody can use
        # 65c1f2b8-…@school.de as an address.
        email_local = _email_local_from_name(first, last) if use_uuid_ids else canonical_pid
        email = _get_email_for_staff(email_local, existing_email, first, last, domain)
        teachers[key] = {
            "person_id": canonical_pid,
            "person_number": person_number,
            "first_name": given,
            "middle_name": middle,
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
                given, middle = _split_given_names(first)
                email = _get_email_for_staff(pid, "", first, last, domain)
                teachers[key] = {
                    "person_id": pid,
                    "person_number": abbr or "",
                    "first_name": given,
                    "middle_name": middle,
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
    # Students are matched by the id Schuldock gives each row. Names are only a
    # fallback for the legacy export, which carries no id — and since two
    # students can share a name, a name that fits more than one matches nobody.
    student_ids = {sr["person_id"] for sr in student_records}
    students_by_name: dict = defaultdict(list)
    for sr in student_records:
        key = (sr["last_name"].strip(), sr.get("first_name", "").strip())
        students_by_name[key].append(sr["person_id"])

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
        # ponytail: three instructor columns; ASM accepts up to instructor_id_15,
        # add columns (writer header + diff) when a class actually needs them.
        if len(teacher_pids) > 3:
            warnings.append(
                f"REVIEW: {an} has {len(teacher_pids)} teachers, but only three are "
                f"exported — not listed for this class: {', '.join(teacher_pids[3:])}"
            )
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
                pid = (row.get("student_id", "") or "").strip()
                if pid not in student_ids:
                    pid = None
                    last, first = row["nachname"].strip(), row["vorname"].strip()
                    candidates = students_by_name.get((last, first), [])
                    if not candidates:
                        first_word = first.split()[:1]
                        candidates = [
                            spid
                            for (sln, sfn), pids in students_by_name.items()
                            if sln == last and sfn.split()[:1] == first_word
                            for spid in pids
                        ]
                    if len(candidates) > 1:
                        warnings.append(
                            f"REVIEW: {row['vorname']} {row['nachname']} in {an} matches "
                            f"{len(candidates)} students by name — enrolled nobody"
                        )
                        continue
                    if candidates:
                        pid = candidates[0]
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


def _collapse_by_id(rows: list, id_field: str, label_field: str) -> tuple[list, list]:
    """Keep one row per id, preferring the undecorated label; report collapses."""
    grouped: dict[str, list[dict]] = OrderedDict()
    for row in rows:
        grouped.setdefault(row[id_field], []).append(row)

    def rank(row: dict) -> tuple:
        # Fewest leading '#' wins, then a stable tie-break on the raw name.
        label = row[label_field]
        return (len(label) - len(label.lstrip("#")), label)

    keep: list = []
    warnings: list = []
    for row_id, members in grouped.items():
        winner, *rest = sorted(members, key=rank)
        keep.append(winner)
        if rest:
            warnings.append(
                f"WARNING: '{winner[label_field]}' and "
                f"{', '.join(repr(r[label_field]) for r in rest)} are the same "
                f"{id_field.replace('_id', '')} ({row_id}); kept one."
            )
    return keep, warnings


def drop_duplicate_classes(
    courses: list,
    classes: list,
    rosters: list,
) -> tuple[list, list, list, list]:
    """Collapse courses/classes that share an id, returning the trimmed tables.

    ``slugify`` ignores the leading '#' Schuldock puts on some offer names, so
    '#Holz Wolke HJ1' and 'Holz Wolke HJ1' produce the same course_id and
    class_id — a duplicate primary key that ASM rejects. They are the same
    course, so one row is kept; the undecorated name wins because it is the
    stable one.

    Rosters are keyed on (class_id, student_id) and are already unique, so no
    enrolment is touched.

    Returns ``(courses, classes, rosters, warnings)``.
    """
    courses, course_warnings = _collapse_by_id(courses, "course_id", "course_number")
    classes, class_warnings = _collapse_by_id(classes, "class_id", "class_number")

    live_classes = {c["class_id"] for c in classes}
    rosters = [r for r in rosters if r["class_id"] in live_classes]

    return courses, classes, rosters, course_warnings + class_warnings
