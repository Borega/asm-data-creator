"""Packaging guardrails for frozen-build hidden imports in asm_generator.spec."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


SPEC_PATH = Path(__file__).resolve().parents[1] / "asm_generator.spec"
REQUIRED_HIDDEN_IMPORTS = {
    "paramiko",
    "keyring",
    "keyring.errors",
}


def _extract_hiddenimports_from_spec_text(spec_text: str) -> list[str]:
    """Return hiddenimports declared in Analysis(...), raising actionable assertions on malformed spec text."""
    marker = "hiddenimports=hiddenimports + ["
    marker_index = spec_text.find(marker)
    assert marker_index != -1, (
        "asm_generator.spec is missing the expected hiddenimports block "
        "('hiddenimports=hiddenimports + [...]')."
    )

    list_start = marker_index + len(marker) - 1  # points at '['
    depth = 0
    list_end = None

    for idx in range(list_start, len(spec_text)):
        char = spec_text[idx]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                list_end = idx + 1
                break

    assert list_end is not None, "Hidden imports list in asm_generator.spec is not properly closed with ']'."

    list_text = spec_text[list_start:list_end]
    try:
        parsed = ast.literal_eval(list_text)
    except (ValueError, SyntaxError) as exc:
        raise AssertionError(
            "Hidden imports list in asm_generator.spec is malformed and could not be parsed."
        ) from exc

    assert isinstance(parsed, list), "Hidden imports block must evaluate to a list literal."
    assert all(isinstance(item, str) for item in parsed), "Hidden imports list must contain only strings."
    return parsed


def test_spec_contains_required_sftp_and_keyring_hidden_imports():
    hidden_imports = _extract_hiddenimports_from_spec_text(SPEC_PATH.read_text(encoding="utf-8"))

    missing = sorted(REQUIRED_HIDDEN_IMPORTS.difference(hidden_imports))
    assert not missing, (
        "asm_generator.spec is missing required SFTP/keyring hidden imports: "
        f"{', '.join(missing)}"
    )


def test_hiddenimports_parser_reports_missing_entries_actionably():
    spec_text = """
a = Analysis(
    ["main.py"],
    hiddenimports=hiddenimports + [
        "paramiko",
        "keyring",
    ],
)
"""

    hidden_imports = _extract_hiddenimports_from_spec_text(spec_text)
    missing = sorted(REQUIRED_HIDDEN_IMPORTS.difference(hidden_imports))

    assert missing == ["keyring.errors"]


def test_hiddenimports_parser_accepts_duplicate_entries_without_false_negative():
    spec_text = """
a = Analysis(
    ["main.py"],
    hiddenimports=hiddenimports + [
        "paramiko",
        "keyring",
        "keyring.errors",
        "paramiko",
    ],
)
"""

    hidden_imports = _extract_hiddenimports_from_spec_text(spec_text)
    missing = sorted(REQUIRED_HIDDEN_IMPORTS.difference(hidden_imports))

    assert missing == []


def test_hiddenimports_parser_fails_for_malformed_spec_structure():
    malformed_spec_text = "a = Analysis(['main.py'], hiddenimports=hiddenimports + [\n    'paramiko',\n"

    with pytest.raises(AssertionError, match="not properly closed"):
        _extract_hiddenimports_from_spec_text(malformed_spec_text)
