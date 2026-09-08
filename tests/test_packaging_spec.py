"""Packaging guardrails for frozen-build hidden imports and data files in asm_generator.spec."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

SPEC_PATH = Path(__file__).resolve().parents[1] / "asm_generator.spec"
REQUIRED_HIDDEN_IMPORTS = {
    "paramiko",
    "keyring",
    "keyring.errors",
}
# Resolved against sys._MEIPASS at runtime, so each must be bundled at the
# bundle root ("."). See gui/app_controller.py::_resolve.
#
# teacher_aliases.json itself is gitignored — it names real staff — so the
# tracked empty stub is what ships, and _resolve falls back to it.
REQUIRED_DATA_FILES = {
    "teacher_aliases.empty.json",
    "subject_map.json",
}


def _extract_list_after(spec_text: str, marker: str) -> list:
    """Return the bracketed list literal following *marker*, with actionable assertions."""
    marker_index = spec_text.find(marker)
    assert marker_index != -1, f"asm_generator.spec is missing the expected block '{marker}...]'."

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

    assert list_end is not None, f"List after '{marker}' is not properly closed with ']'."

    list_text = spec_text[list_start:list_end]
    try:
        parsed = ast.literal_eval(list_text)
    except (ValueError, SyntaxError) as exc:
        raise AssertionError(
            f"List after '{marker}' in asm_generator.spec is malformed and could not be parsed."
        ) from exc

    assert isinstance(parsed, list), f"Block '{marker}' must evaluate to a list literal."
    return parsed


def _extract_hiddenimports_from_spec_text(spec_text: str) -> list[str]:
    """Return hiddenimports declared in Analysis(...)."""
    parsed = _extract_list_after(spec_text, "hiddenimports=hiddenimports + [")
    assert all(isinstance(item, str) for item in parsed), "Hidden imports list must contain only strings."
    return parsed


def _extract_datas_from_spec_text(spec_text: str) -> list[tuple[str, str]]:
    """Return (source, destination) data entries declared in Analysis(...)."""
    parsed = _extract_list_after(spec_text, "datas=datas + [")
    assert all(
        isinstance(item, tuple) and len(item) == 2 for item in parsed
    ), "datas entries must be (source, destination) pairs."
    return parsed


def test_spec_contains_required_sftp_and_keyring_hidden_imports():
    hidden_imports = _extract_hiddenimports_from_spec_text(SPEC_PATH.read_text(encoding="utf-8"))

    missing = sorted(REQUIRED_HIDDEN_IMPORTS.difference(hidden_imports))
    assert not missing, (
        "asm_generator.spec is missing required SFTP/keyring hidden imports: "
        f"{', '.join(missing)}"
    )


def test_spec_bundles_runtime_data_files_at_bundle_root():
    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    datas = _extract_datas_from_spec_text(spec_text)

    # Destination must be "." so sys._MEIPASS / <name> resolves at runtime.
    bundled_at_root = {Path(src).name for src, dest in datas if dest == "."}
    missing = sorted(REQUIRED_DATA_FILES.difference(bundled_at_root))
    assert not missing, (
        "asm_generator.spec does not bundle these files at the bundle root, so a frozen "
        f"build cannot generate with default settings: {', '.join(missing)}"
    )

    # A spec entry pointing at a file that no longer exists fails the build, not the app.
    for name in REQUIRED_DATA_FILES:
        source = SPEC_PATH.parent / name
        assert source.is_file(), f"asm_generator.spec bundles '{name}', but it is missing from the repo."


def test_every_bundled_file_is_tracked_in_git():
    """Existing locally is not enough — CI and other schools build from a clean clone.

    This is the check that was missing: teacher_aliases.json and locations.csv
    sat in the working tree while being gitignored, so the spec looked fine here
    and PyInstaller would have failed on a fresh checkout.
    """
    repo = SPEC_PATH.parent
    try:
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=repo, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - no git available
        pytest.skip("git is not available")
    if tracked.returncode != 0:  # pragma: no cover - not a git checkout
        pytest.skip("not a git checkout")

    tracked_names = {Path(line).as_posix() for line in tracked.stdout.splitlines() if line}
    datas = _extract_datas_from_spec_text(SPEC_PATH.read_text(encoding="utf-8"))

    untracked = sorted(
        src for src, _dest in datas
        if (repo / src).exists() and Path(src).as_posix() not in tracked_names
    )
    assert not untracked, (
        "asm_generator.spec bundles files that are not tracked in git, so the build "
        f"breaks on a clean clone even though it works here: {', '.join(untracked)}"
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
