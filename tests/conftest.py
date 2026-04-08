"""Shared pytest fixtures for asm_generator tests."""
import pytest


STUDENT_HEADER = "externKey\tlongName\tforeName\tklasse.name\n"


def make_student_tsv(rows: list) -> str:
    """Build a tab-separated student CSV string."""
    lines = [STUDENT_HEADER]
    for r in rows:
        lines.append(
            f"{r.get('externKey','')}\t{r.get('longName','')}\t"
            f"{r.get('foreName','')}\t{r.get('klasse.name','')}\n"
        )
    return "".join(lines)


MONOLITH_HEADER = (
    "Nachname;Vorname;Rufname;Geburtstag;Geschlecht;Kürzel;Klassen;Klassennamen;Angebote;"
    "Manuelle Gruppen;E-Mail-Adressen der weiteren Schulen;Rolle;Interne ID;Export ID;Gültig bis;Löschdatum\n"
)


def make_monolith_csv(rows: list[dict]) -> str:
    """Build a semicolon-separated monolith CSV string."""
    fields = [
        "Nachname",
        "Vorname",
        "Rufname",
        "Geburtstag",
        "Geschlecht",
        "Kürzel",
        "Klassen",
        "Klassennamen",
        "Angebote",
        "Manuelle Gruppen",
        "E-Mail-Adressen der weiteren Schulen",
        "Rolle",
        "Interne ID",
        "Export ID",
        "Gültig bis",
        "Löschdatum",
    ]
    lines = [MONOLITH_HEADER]
    for row in rows:
        vals = [str(row.get(k, "")) for k in fields]
        lines.append(";".join(vals) + "\n")
    return "".join(lines)
