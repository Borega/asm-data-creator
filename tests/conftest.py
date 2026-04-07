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
