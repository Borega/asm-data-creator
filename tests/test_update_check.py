"""update_check: version ordering, offline behaviour, verification and folder safety."""
import hashlib
import io
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import zipfile

import pytest

import update_check as uc


def _release(payload=b"", **kw):
    fields = dict(tag="v1.1.7", url=uc.DOWNLOAD_PREFIX + "v1.1.7/ASM-Generator-v1.1.7.zip",
                  size=len(payload), sha256=hashlib.sha256(payload).hexdigest(), page="")
    fields.update(kw)
    return uc.Release(**fields)


def test_versions_compare_as_numbers_not_strings():
    assert uc.is_newer("v1.1.10", "v1.1.9")
    assert not uc.is_newer("v1.1.9", "v1.1.10")
    assert not uc.is_newer("v1.1.7", "v1.1.7")
    assert not uc.is_newer("v1.1.7", "0.0.0-dev")
    assert not uc.is_newer("nightly", "v1.1.7")


def test_development_build_never_goes_online(monkeypatch):
    monkeypatch.setattr(uc, "current_version", lambda: "0.0.0-dev")
    monkeypatch.setattr(uc, "fetch_latest", lambda: pytest.fail("must not fetch"))
    assert uc.check()[0] is None


def test_offline_is_a_status_not_an_error(monkeypatch):
    def offline():
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(uc, "current_version", lambda: "v1.1.6")
    monkeypatch.setattr(uc, "fetch_latest", offline)
    release, message = uc.check()
    assert release is None and "Could not check" in message


def _api(monkeypatch, body):
    monkeypatch.setattr(uc, "_open", lambda url, accept: io.BytesIO(json.dumps(body).encode()))


def test_fetch_latest_reads_asset_and_digest(monkeypatch):
    _api(monkeypatch, {"tag_name": "v1.1.7", "html_url": "page", "assets": [{
        "name": "ASM-Generator-v1.1.7.zip", "size": 5, "digest": "sha256:ABC",
        "browser_download_url": uc.DOWNLOAD_PREFIX + "v1.1.7/ASM-Generator-v1.1.7.zip"}]})
    release = uc.fetch_latest()
    assert (release.tag, release.size, release.sha256) == ("v1.1.7", 5, "abc")


def test_fetch_latest_refuses_a_download_outside_the_repo(monkeypatch):
    _api(monkeypatch, {"tag_name": "v1.1.7", "assets": [{
        "name": "ASM-Generator-v1.1.7.zip", "browser_download_url": "https://evil.example/x.zip"}]})
    with pytest.raises(RuntimeError, match="outside"):
        uc.fetch_latest()


def test_download_keeps_only_a_verified_file(monkeypatch, tmp_path):
    monkeypatch.setattr(uc, "_open", lambda url, accept: io.BytesIO(b"payload"))
    good, bad = tmp_path / "good", tmp_path / "bad"
    good.mkdir()
    bad.mkdir()
    assert uc.download(_release(b"payload"), good).read_bytes() == b"payload"

    with pytest.raises(RuntimeError, match="checksum"):
        uc.download(_release(b"payload", sha256=hashlib.sha256(b"other").hexdigest()), bad)
    assert list(bad.iterdir()) == [], "a file failing verification must not be left behind"

    with pytest.raises(RuntimeError, match="No checksum"):
        uc.download(_release(b"payload", sha256=""), bad)


def _app_folder(tmp_path, *extra):
    target = tmp_path / "ASM-Generator"
    (target / "_internal").mkdir(parents=True)
    (target / uc.EXE_NAME).write_bytes(b"exe")
    for name in extra:
        (target / name).write_text("x")
    return target


def test_install_refuses_a_folder_holding_other_files(tmp_path):
    assert uc.install_problem(_release(b"x"), _app_folder(tmp_path)) == ""
    assert "other files" in uc.install_problem(_release(b"x"), _app_folder(tmp_path / "b", "Hausaufgaben.docx"))
    assert "checksum" in uc.install_problem(_release(b"x", sha256=""), _app_folder(tmp_path / "c"))


def _zip(tmp_path, names):
    path = tmp_path / "release.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, b"x")
    return path


def test_stage_unpacks_beside_the_program_folder(tmp_path):
    target = _app_folder(tmp_path)
    staging = uc.stage(_zip(tmp_path, [uc.EXE_NAME, "_internal/base_library.zip"]), target)
    assert staging == tmp_path / "ASM-Generator.update"
    assert (staging / uc.EXE_NAME).is_file()


@pytest.mark.skipif(sys.platform != "win32", reason="the swap helper is a Windows batch script")
def test_swap_waits_for_the_running_app_then_replaces_the_folder(tmp_path):
    """The real helper, a real process holding the lock as the app does, a path with umlaut and brackets."""
    root = tmp_path / "Prüf Ordner (Schule)"
    target, staging = root / "ASM-Generator", root / "ASM-Generator.update"
    for folder, marker in ((target, "old"), (staging, "new")):
        (folder / "_internal").mkdir(parents=True)
        # rundll32 without arguments exits silently — a harmless stand-in for the relaunch.
        shutil.copy(r"C:\Windows\System32\rundll32.exe", folder / uc.EXE_NAME)
        (folder / "_internal" / "marker.txt").write_text(marker)

    lock = tmp_path / "app.lock"
    app = subprocess.Popen(  # the "running app": holds the lock open for 5 s, then exits
        [sys.executable, "-c", "import sys, time; f = open(sys.argv[1], 'w'); time.sleep(5)", str(lock)],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        while not lock.exists():
            time.sleep(0.05)
        uc.launch_swap(target, staging, "v1.1.6", lock=lock)
        time.sleep(3)
        assert (target / "_internal" / "marker.txt").read_text() == "old", "swapped while the app still ran"
    finally:
        app.wait()

    deadline = time.time() + 60
    while staging.exists() and time.time() < deadline:
        time.sleep(0.5)
    assert (target / "_internal" / "marker.txt").read_text() == "new"
    assert (root / "ASM-Generator.old-v1.1.6" / "_internal" / "marker.txt").read_text() == "old"


@pytest.mark.parametrize("names", [["_internal/x"], ["../evil.exe", uc.EXE_NAME, "_internal/x"]])
def test_stage_rejects_a_broken_or_unsafe_archive(tmp_path, names):
    target = _app_folder(tmp_path)
    with pytest.raises(RuntimeError):
        uc.stage(_zip(tmp_path, names), target)
    assert not uc.staging_dir(target).exists()
