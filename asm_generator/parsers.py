"""CSV parsers for student master and course-enrollment export files."""
from __future__ import annotations
from pathlib import Path


def parse_students(paths: list) -> list:
    """Parse one or more tab-separated student master CSV files.

    Records from later files overwrite earlier records with the same externKey.
    Raises ValueError if paths is empty.
    """
    raise NotImplementedError


def parse_export(paths: list) -> list:
    """Parse one or more semicolon-separated course-enrollment export files.

    Sections from later files are appended after sections from earlier files.
    Raises ValueError if paths is empty.
    """
    raise NotImplementedError
