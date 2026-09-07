"""Startup SFTP probe must not block the GUI thread.

``AppController.__init__`` used to call ``check_connection`` inline, which is a
blocking TCP connect with a 15 s timeout — on a network that filters outbound
port 22 the window did not appear until the timeout elapsed.  These tests pin
the asynchronous replacement: dispatch off-thread, apply on the GUI thread, and
ignore results from probes that a newer one has superseded.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import gui.app_controller as ac_module
from gui.workers import SftpStatusWorker


class _PageDouble:
    def __init__(self) -> None:
        self.calls: list[tuple[bool, str]] = []

    def set_upload_available(self, ready: bool, message: str) -> None:
        self.calls.append((ready, message))

    def set_sftp_status(self, ready: bool, message: str) -> None:
        self.calls.append((ready, message))


class _Dispatched(list):
    """Workers the controller handed off, captured instead of really threaded."""


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch) -> _Dispatched:
    started = _Dispatched()
    monkeypatch.setattr(SftpStatusWorker, "start", lambda worker: started.append(worker))
    return started


def _make_controller(monkeypatch: pytest.MonkeyPatch, *, username: str, check_fn, password="secret"):
    monkeypatch.setattr(ac_module.SettingsStore, "load", lambda: {"sftp_username": username})
    monkeypatch.setattr(ac_module, "is_keyring_available", lambda: True)
    monkeypatch.setattr(ac_module, "get_password", lambda _username: password)
    monkeypatch.setattr(ac_module, "check_sftp_connection", check_fn)
    return ac_module.AppController(main_window=SimpleNamespace())


# ---------------------------------------------------------------------------
# Startup dispatch
# ---------------------------------------------------------------------------


def test_startup_does_not_call_blocking_check_on_gui_thread(
    pool: _Dispatched, monkeypatch: pytest.MonkeyPatch
):
    def _must_not_run(_username: str, _password: str):
        raise AssertionError("check_connection ran inline during __init__")

    controller = _make_controller(monkeypatch, username="upload-user", check_fn=_must_not_run)

    assert len(pool) == 1
    assert controller.get_sftp_status() == (
        False,
        ac_module.AppController.SFTP_CHECK_PENDING_MESSAGE,
    )


def test_startup_dispatches_worker_with_resolved_credentials(
    pool: _Dispatched, monkeypatch: pytest.MonkeyPatch
):
    _make_controller(
        monkeypatch, username="upload-user", check_fn=lambda u, p: (True, "Connected.")
    )

    worker = pool[0]
    assert isinstance(worker, SftpStatusWorker)
    assert worker._username == "upload-user"
    assert worker._password == "secret"


def test_startup_without_username_resolves_synchronously_and_dispatches_nothing(
    pool: _Dispatched, monkeypatch: pytest.MonkeyPatch
):
    controller = _make_controller(
        monkeypatch, username="", check_fn=lambda u, p: (True, "Connected.")
    )

    assert pool == []
    assert controller.get_sftp_status() == (False, "Missing SFTP username.")


def test_startup_without_password_resolves_synchronously_and_dispatches_nothing(
    pool: _Dispatched, monkeypatch: pytest.MonkeyPatch
):
    controller = _make_controller(
        monkeypatch, username="upload-user", check_fn=lambda u, p: (True, "ok"), password=""
    )

    assert pool == []
    assert controller.get_sftp_status() == (False, "Missing SFTP password.")


def test_upload_stays_disabled_while_probe_is_in_flight(
    pool: _Dispatched, monkeypatch: pytest.MonkeyPatch
):
    controller = _make_controller(
        monkeypatch, username="upload-user", check_fn=lambda u, p: (True, "ok")
    )
    ready, _message = controller.get_sftp_status()

    assert ready is False


# ---------------------------------------------------------------------------
# Result delivery
# ---------------------------------------------------------------------------


def test_worker_result_is_applied_and_pushed_to_pages(
    pool: _Dispatched, monkeypatch: pytest.MonkeyPatch
):
    controller = _make_controller(
        monkeypatch, username="upload-user", check_fn=lambda u, p: (True, "Connected.")
    )
    diff_page, settings_page = _PageDouble(), _PageDouble()
    controller._diff_page = diff_page
    controller._settings_page = settings_page

    pool[0].run()  # what the daemon probe thread would do

    assert controller.get_sftp_status() == (True, "Connected.")
    assert diff_page.calls[-1] == (True, "Connected.")
    assert settings_page.calls[-1] == (True, "Connected.")


def test_worker_timeout_result_disables_upload_with_message(
    pool: _Dispatched, monkeypatch: pytest.MonkeyPatch
):
    controller = _make_controller(
        monkeypatch,
        username="upload-user",
        check_fn=lambda u, p: (False, "Connection timed out (host:22)."),
    )

    pool[0].run()

    assert controller.get_sftp_status() == (False, "Connection timed out (host:22).")


def test_stale_worker_result_is_ignored(pool: _Dispatched, monkeypatch: pytest.MonkeyPatch):
    controller = _make_controller(
        monkeypatch, username="upload-user", check_fn=lambda u, p: (True, "Stale connect.")
    )
    stale_worker = pool[0]

    # A newer authoritative update lands while the startup probe is still running.
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "")
    controller._refresh_sftp_status(check_connection=True)
    assert controller.get_sftp_status() == (False, "Missing SFTP password.")

    stale_worker.run()

    assert controller.get_sftp_status() == (False, "Missing SFTP password.")


def test_saving_credentials_supersedes_an_in_flight_probe(
    pool: _Dispatched, monkeypatch: pytest.MonkeyPatch
):
    controller = _make_controller(
        monkeypatch, username="upload-user", check_fn=lambda u, p: (True, "Stale connect.")
    )
    stale_worker = pool[0]

    controller.save_sftp_credentials("upload-user", "", "")
    assert controller.get_sftp_status() == (False, "Missing SFTP username.")

    stale_worker.run()

    assert controller.get_sftp_status() == (False, "Missing SFTP username.")


# ---------------------------------------------------------------------------
# Worker contract
# ---------------------------------------------------------------------------


def _collect(worker: SftpStatusWorker) -> list[tuple[int, bool, str]]:
    seen: list[tuple[int, bool, str]] = []
    worker.signals.finished.connect(lambda t, r, m: seen.append((t, r, m)))
    worker.run()
    return seen


def test_worker_echoes_token_and_normalizes_success():
    worker = SftpStatusWorker(lambda u, p: (True, "Connected."), "user", "pw", 7)

    assert _collect(worker) == [(7, True, "Connected.")]


def test_worker_coerces_non_tuple_result_to_failure():
    worker = SftpStatusWorker(lambda u, p: "nonsense", "user", "pw", 1)

    assert _collect(worker) == [(1, False, "Unexpected SFTP connection response.")]


def test_worker_coerces_truthy_non_boolean_ready_to_failure():
    worker = SftpStatusWorker(lambda u, p: ("yes", "Connected."), "user", "pw", 1)

    assert _collect(worker) == [(1, False, "Connected.")]


def test_worker_converts_unexpected_exception_into_failure_signal():
    def _boom(_u: str, _p: str):
        raise RuntimeError("socket exploded")

    assert _collect(SftpStatusWorker(_boom, "user", "pw", 3)) == [
        (3, False, "Connection error: socket exploded")
    ]


def test_worker_replaces_empty_message_with_fallback_copy():
    worker = SftpStatusWorker(lambda u, p: (False, ""), "user", "pw", 2)

    assert _collect(worker) == [(2, False, "Unexpected SFTP connection response.")]
