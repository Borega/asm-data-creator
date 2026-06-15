from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

TIMESTAMP_PATTERN = re.compile(r"^\d{8}_\d{6}$")
DEFAULT_RETENTION_LIMIT = 5

logger = logging.getLogger(__name__)


def get_backup_root(local_appdata: str | None = None) -> Path:
    """Return the backup root under LOCALAPPDATA.

    Contract path:
      %LOCALAPPDATA%/ASM-Generator/backups

    Raises:
        RuntimeError: if LOCALAPPDATA is missing or blank.
    """
    if local_appdata is None:
        local_appdata = os.getenv("LOCALAPPDATA")

    if local_appdata is None or not str(local_appdata).strip():
        raise RuntimeError("LOCALAPPDATA environment variable is missing or empty.")

    return Path(str(local_appdata).strip()) / "ASM-Generator" / "backups"


def create_backup(
    source_zip: str | Path,
    *,
    retention_limit: int = DEFAULT_RETENTION_LIMIT,
) -> Path:
    """Create a timestamped local backup for the given ZIP file.

    The ZIP is copied to:
      %LOCALAPPDATA%/ASM-Generator/backups/YYYYMMDD_HHMMSS/<zip-name>

    Create/copy failures are raised to the caller. Retention prune failures are
    warning-only and do not block backup creation.

    Returns:
        Path to the copied backup ZIP.
    """
    source = Path(source_zip)
    if not source.exists():
        raise FileNotFoundError(f"Backup source ZIP does not exist: {source}")
    if not source.is_file():
        raise FileNotFoundError(f"Backup source ZIP is not a file: {source}")

    backup_root = get_backup_root()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / timestamp

    backup_dir.mkdir(parents=True, exist_ok=False)

    destination = backup_dir / source.name
    try:
        shutil.copy2(source, destination)
    except Exception:
        try:
            shutil.rmtree(backup_dir)
        except OSError:
            pass
        raise

    prune_backups(backup_root, keep_latest=retention_limit)
    return destination


def prune_backups(backup_root: str | Path, *, keep_latest: int = DEFAULT_RETENTION_LIMIT) -> None:
    """Keep only the newest `keep_latest` timestamped backup directories.

    Failures while scanning/deleting old backups are warning-only.
    Non-timestamp directory names are ignored.
    """
    root = Path(backup_root)

    try:
        timestamp_dirs = sorted(
            [
                path
                for path in root.iterdir()
                if path.is_dir() and TIMESTAMP_PATTERN.fullmatch(path.name)
            ],
            key=lambda path: path.name,
        )
    except FileNotFoundError:
        return
    except Exception as exc:
        logger.warning("Failed to inspect backups for pruning in '%s': %s", root, exc)
        return

    if keep_latest < 0:
        keep_latest = 0

    to_delete = timestamp_dirs[:-keep_latest] if keep_latest else timestamp_dirs
    for backup_dir in to_delete:
        try:
            shutil.rmtree(backup_dir)
        except Exception as exc:
            logger.warning("Failed to prune backup directory '%s': %s", backup_dir, exc)
