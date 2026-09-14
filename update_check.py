"""Finds a newer release on GitHub and installs it over this copy of the app.

Only a frozen (PyInstaller) build updates itself. Run from source there is no
stamped VERSION to compare and no program folder to replace.

A running Windows program cannot overwrite its own files, so installing is
split in two: this process downloads, verifies and unpacks the release next to
the program folder, then starts a small helper and quits. Once the app has
exited, the helper renames the old folder to a backup, moves the new one into
place and starts it. If the swap fails, the old folder is put back.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

REPO = "Borega/asm-data-creator"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
EXE_NAME = "ASM-Generator.exe"
_TIMEOUT = 20  # seconds per blocking read, not for the whole download
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass
class Release:
    tag: str
    url: str
    size: int
    sha256: str  # lowercase hex; "" when GitHub published no digest
    page: str


def current_version() -> str:
    """The release tag CI stamped into VERSION; "" or "0.0.0-dev" from source."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    try:
        return (base / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def parse_version(tag: str) -> tuple[int, int, int] | None:
    m = _VERSION_RE.match((tag or "").strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def is_newer(latest: str, current: str) -> bool:
    """Compared as integers: as strings "1.1.9" would beat "1.1.10"."""
    new, cur = parse_version(latest), parse_version(current)
    return bool(new and cur and new > cur)


def _open(url: str, accept: str):
    # GitHub's API rejects requests without a User-Agent (403).
    request = urllib.request.Request(url, headers={"User-Agent": "ASM-Generator-updater", "Accept": accept})
    return urllib.request.urlopen(request, timeout=_TIMEOUT)


def fetch_latest() -> Release:
    with _open(LATEST_URL, "application/vnd.github+json") as response:
        data = json.load(response)
    tag = str(data.get("tag_name", ""))
    wanted = f"ASM-Generator-{tag}.zip"
    for asset in data.get("assets", []):
        if asset.get("name") != wanted:
            continue
        url = str(asset.get("browser_download_url", ""))
        if not url.startswith(DOWNLOAD_PREFIX):
            raise RuntimeError(f"Release {tag} points outside {REPO}: {url}")
        digest = str(asset.get("digest") or "")
        return Release(
            tag=tag,
            url=url,
            size=int(asset.get("size") or 0),
            sha256=digest[len("sha256:"):].lower() if digest.startswith("sha256:") else "",
            page=str(data.get("html_url", "")),
        )
    raise RuntimeError(f"Release {tag} has no {wanted}.")


def check() -> tuple[Release | None, str]:
    """(newer release or None, status message). Never raises — offline is normal."""
    current = current_version()
    if not parse_version(current):
        return None, "Development build — updates are only checked in the installed app."
    try:
        latest = fetch_latest()
    except Exception as exc:  # noqa: BLE001 - any failure just means "unknown"
        return None, f"Could not check for updates: {exc}"
    if is_newer(latest.tag, current):
        return latest, f"Version {latest.tag} is available (installed: {current})."
    return None, f"Up to date ({current})."


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _writable(folder: Path) -> bool:
    try:
        with tempfile.TemporaryFile(dir=folder):
            return True
    except OSError:
        return False


def install_problem(release: Release, target: Path | None = None) -> str:
    """Why this copy cannot replace itself; "" when it can."""
    if target is None:
        if not getattr(sys, "frozen", False):
            return "Only the installed app can update itself."
        target = install_dir()
    if not release.sha256:
        return "GitHub published no checksum for this release, so the download cannot be verified."
    # The whole folder gets renamed. If the app was unpacked straight into
    # Downloads or the desktop, that folder holds other files and must never
    # be moved — so anything besides the app itself stops the update.
    names = {p.name.lower() for p in target.iterdir()}
    if EXE_NAME.lower() not in names or names - {EXE_NAME.lower(), "_internal"}:
        return (
            f"The folder {target} contains other files besides the app, so it is not "
            "replaced automatically. Move the app into a folder of its own, or update by hand."
        )
    if not (_writable(target) and _writable(target.parent)):
        return f"No write access to {target.parent} (for example under Program Files)."
    if release.size and shutil.disk_usage(target.parent).free < release.size * 4:
        return "Not enough free disk space to download and unpack the update."
    return ""


def download(release: Release, folder: Path, progress=None, cancelled=lambda: False) -> Path:
    """Download the release ZIP into *folder* and verify its SHA-256. Raises on any problem."""
    if not release.sha256:
        raise RuntimeError("No checksum published for this release — not downloading.")
    path = folder / f"ASM-Generator-{release.tag}.zip"
    digest = hashlib.sha256()
    done = 0
    try:
        with _open(release.url, "application/octet-stream") as response, open(path, "wb") as out:
            while chunk := response.read(1 << 20):
                if cancelled():
                    raise RuntimeError("Update cancelled.")
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress and release.size:
                    progress(min(100, done * 100 // release.size))
        if digest.hexdigest() != release.sha256:
            raise RuntimeError("The download does not match the checksum GitHub published — not installed.")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def staging_dir(target: Path) -> Path:
    return target.parent / f"{target.name}.update"


def stage(zip_path: Path, target: Path) -> Path:
    """Unpack next to *target* (same drive, so the swap is a rename) and check the layout."""
    staging = staging_dir(target)
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for name in archive.namelist():
                if name.startswith(("/", "\\")) or ".." in Path(name).parts or ":" in name:
                    raise RuntimeError(f"Unsafe path in the release archive: {name}")
            archive.extractall(staging)
        if not (staging / EXE_NAME).is_file() or not (staging / "_internal").is_dir():
            raise RuntimeError("The downloaded release does not contain the app — not installed.")
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging


# How the helper knows the app has exited: the app keeps a lock file open for
# the rest of its life, and Windows refuses to rename a file another process
# holds open. Renaming the program folder is no such signal — current Windows
# allows it while the program inside is still running.
#
# ASCII only, and every path arrives as an argument: cmd reads a script in the
# OEM code page, which would mangle a path like C:\Users\Jürgen embedded here.
_SWAP_SCRIPT = r"""@echo off
rem %1 program folder, %2 new folder, %3 backup folder, %4 lock file held by the app
set tries=0
:wait
move "%~4" "%~4.released" >nul 2>&1 && goto swap
set /a tries+=1
rem The app never exited: leave everything as it is.
if %tries% geq 120 exit /b 1
ping -n 2 127.0.0.1 >nul
goto wait
:swap
del "%~4.released" >nul 2>&1
set tries=0
:rename
move "%~1" "%~3" >nul 2>&1 && goto place
set /a tries+=1
if %tries% geq 30 goto relaunch
ping -n 2 127.0.0.1 >nul
goto rename
:place
move "%~2" "%~1" >nul 2>&1 || move "%~3" "%~1" >nul 2>&1
:relaunch
start "" "%~1\ASM-Generator.exe"
"""

_held_lock = None  # open until this process exits; see _SWAP_SCRIPT


def launch_swap(target: Path, staging: Path, current: str, lock: Path | None = None) -> None:
    """Start the helper that replaces *target* with *staging* once the app has exited.

    Without *lock*, this process creates and holds the lock itself — the normal
    case. Tests pass the lock of a separate process they control.
    """
    global _held_lock
    temp = Path(tempfile.gettempdir())
    if lock is None:
        lock = temp / "asm-generator-update.lock"
        Path(f"{lock}.released").unlink(missing_ok=True)
        _held_lock = open(lock, "w")  # noqa: SIM115 - must outlive this function
    # ponytail: keeps only the most recent backup; each one is a full copy (~250 MB).
    for old in target.parent.glob(f"{target.name}.old-*"):
        shutil.rmtree(old, ignore_errors=True)
    backup = target.parent / f"{target.name}.old-{current or 'previous'}"
    script = temp / "asm-generator-update.cmd"
    script.write_text(_SWAP_SCRIPT, encoding="ascii")
    # /s strips exactly the outer quotes, so quoted paths with spaces survive.
    command = f'cmd.exe /d /s /c ""{script}" "{target}" "{staging}" "{backup}" "{lock}""'
    subprocess.Popen(
        command,
        cwd=tempfile.gettempdir(),  # never inside the folder being renamed
        close_fds=True,
        # A hidden console rather than none, so ping inside the script behaves.
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
