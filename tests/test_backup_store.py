from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pytest

import backup_store


class _FrozenDateTime:
    @staticmethod
    def now() -> datetime:
        return datetime(2026, 4, 10, 12, 34, 56)


def _touch_zip(path: Path) -> Path:
    path.write_bytes(b"zip-bytes")
    return path


def _make_timestamp_dirs(root: Path, names: list[str]) -> None:
    for name in names:
        (root / name).mkdir(parents=True, exist_ok=True)


def test_get_backup_root_uses_localappdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))

    root = backup_store.get_backup_root()

    assert root == (tmp_path / "AppData" / "Local" / "ASM-Generator" / "backups")


@pytest.mark.parametrize("value", [None, "", "   "])
def test_get_backup_root_raises_when_localappdata_missing_or_blank(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
    else:
        monkeypatch.setenv("LOCALAPPDATA", value)

    with pytest.raises(RuntimeError, match="LOCALAPPDATA environment variable is missing or empty"):
        backup_store.get_backup_root()


def test_create_backup_copies_zip_into_timestamped_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_zip = _touch_zip(tmp_path / "asm_export.zip")
    local_appdata = tmp_path / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(backup_store, "datetime", _FrozenDateTime)

    destination = backup_store.create_backup(source_zip)

    expected = local_appdata / "ASM-Generator" / "backups" / "20260410_123456" / "asm_export.zip"
    assert destination == expected
    assert destination.read_bytes() == b"zip-bytes"


def test_create_backup_raises_for_missing_source_zip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))

    missing_zip = tmp_path / "missing.zip"
    with pytest.raises(FileNotFoundError, match="Backup source ZIP does not exist"):
        backup_store.create_backup(missing_zip)


def test_create_backup_raises_when_mkdir_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_zip = _touch_zip(tmp_path / "asm_export.zip")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))

    def _raise_mkdir(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
        raise PermissionError("no permission")

    monkeypatch.setattr(backup_store.Path, "mkdir", _raise_mkdir)

    with pytest.raises(PermissionError, match="no permission"):
        backup_store.create_backup(source_zip)


def test_create_backup_raises_when_copy_fails_and_cleans_timestamp_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_zip = _touch_zip(tmp_path / "asm_export.zip")
    local_appdata = tmp_path / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(backup_store, "datetime", _FrozenDateTime)

    def _raise_copy(*args, **kwargs):  # noqa: ANN002,ANN003
        raise OSError("copy failed")

    monkeypatch.setattr(backup_store.shutil, "copy2", _raise_copy)

    with pytest.raises(OSError, match="copy failed"):
        backup_store.create_backup(source_zip)

    timestamp_dir = local_appdata / "ASM-Generator" / "backups" / "20260410_123456"
    assert not timestamp_dir.exists()


def test_prune_backups_keeps_exactly_five_timestamp_dirs(
    tmp_path: Path,
) -> None:
    backup_root = tmp_path / "ASM-Generator" / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    _make_timestamp_dirs(
        backup_root,
        [
            "20260410_120000",
            "20260410_120100",
            "20260410_120200",
            "20260410_120300",
            "20260410_120400",
        ],
    )

    backup_store.prune_backups(backup_root, keep_latest=5)

    names = sorted(path.name for path in backup_root.iterdir())
    assert names == [
        "20260410_120000",
        "20260410_120100",
        "20260410_120200",
        "20260410_120300",
        "20260410_120400",
    ]


def test_prune_backups_removes_oldest_timestamp_dir_and_ignores_non_timestamp(
    tmp_path: Path,
) -> None:
    backup_root = tmp_path / "ASM-Generator" / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    _make_timestamp_dirs(
        backup_root,
        [
            "20260410_120000",
            "20260410_120100",
            "20260410_120200",
            "20260410_120300",
            "20260410_120400",
            "20260410_120500",
        ],
    )
    (backup_root / "notes").mkdir(parents=True, exist_ok=True)

    backup_store.prune_backups(backup_root, keep_latest=5)

    names = sorted(path.name for path in backup_root.iterdir())
    assert names == [
        "20260410_120100",
        "20260410_120200",
        "20260410_120300",
        "20260410_120400",
        "20260410_120500",
        "notes",
    ]


def test_prune_failures_emit_warning_and_do_not_raise(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    source_zip = _touch_zip(tmp_path / "asm_export.zip")
    local_appdata = tmp_path / "AppData" / "Local"
    backup_root = local_appdata / "ASM-Generator" / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    _make_timestamp_dirs(
        backup_root,
        [
            "20260410_120000",
            "20260410_120100",
            "20260410_120200",
            "20260410_120300",
            "20260410_120400",
        ],
    )

    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(backup_store, "datetime", _FrozenDateTime)
    real_rmtree = backup_store.shutil.rmtree

    def _flaky_rmtree(path, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
        if Path(path).name == "20260410_120000":
            raise OSError("locked")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(backup_store.shutil, "rmtree", _flaky_rmtree)

    with caplog.at_level(logging.WARNING):
        destination = backup_store.create_backup(source_zip)

    assert destination.exists()
    assert "Failed to prune backup directory" in caplog.text
    assert "20260410_120000" in caplog.text


def test_prune_scan_failure_is_warning_only(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    backup_root = tmp_path / "ASM-Generator" / "backups"

    def _raise_iterdir(self):  # noqa: ANN001
        raise OSError("scan failed")

    monkeypatch.setattr(backup_store.Path, "iterdir", _raise_iterdir)

    with caplog.at_level(logging.WARNING):
        backup_store.prune_backups(backup_root)

    assert "Failed to inspect backups for pruning" in caplog.text
    assert "scan failed" in caplog.text
