"""Controller-level SFTP lifecycle tests.

These tests pin startup/reload/save/test status transitions in ``AppController`` so
upload gating and Settings status messaging remain deterministic.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import gui.app_controller as ac_module


class _PageDouble:
    def __init__(self) -> None:
        self.calls: list[tuple[bool, str]] = []

    def set_upload_available(self, ready: bool, message: str) -> None:
        self.calls.append((ready, message))

    def set_sftp_status(self, ready: bool, message: str) -> None:
        self.calls.append((ready, message))


@pytest.fixture
def controller(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ac_module.SettingsStore, "load", lambda: {"sftp_username": ""})
    monkeypatch.setattr(ac_module, "is_keyring_available", lambda: True)
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "")
    monkeypatch.setattr(
        ac_module,
        "check_sftp_connection",
        lambda _username, _password: (True, "Connected."),
    )
    return ac_module.AppController(main_window=SimpleNamespace())


def test_startup_missing_username_sets_not_ready_state(controller):
    assert controller.get_sftp_status() == (False, "Missing SFTP username.")


def test_refresh_status_keyring_unavailable_sets_status(controller, monkeypatch: pytest.MonkeyPatch):
    controller._settings["sftp_username"] = "upload-user"
    monkeypatch.setattr(ac_module, "is_keyring_available", lambda: False)

    controller._refresh_sftp_status(check_connection=True)

    assert controller.get_sftp_status() == (False, "Secure keyring backend is unavailable.")


def test_refresh_status_surfaces_credential_error(controller, monkeypatch: pytest.MonkeyPatch):
    controller._settings["sftp_username"] = "upload-user"

    def _raise(_username: str) -> str:
        raise ac_module.CredentialError("backend read failed")

    monkeypatch.setattr(ac_module, "get_password", _raise)

    controller._refresh_sftp_status(check_connection=True)

    assert controller.get_sftp_status() == (False, "Credential error: backend read failed")


def test_refresh_status_missing_password_sets_not_ready(controller, monkeypatch: pytest.MonkeyPatch):
    controller._settings["sftp_username"] = "upload-user"
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "")

    controller._refresh_sftp_status(check_connection=True)

    assert controller.get_sftp_status() == (False, "Missing SFTP password.")


def test_refresh_status_with_connection_result_is_propagated(controller, monkeypatch: pytest.MonkeyPatch):
    controller._settings["sftp_username"] = "upload-user"
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "secret")
    monkeypatch.setattr(
        ac_module,
        "check_sftp_connection",
        lambda _username, _password: (False, "Connection timed out (upload.appleschoolcontent.com:22)."),
    )

    controller._refresh_sftp_status(check_connection=True)

    assert controller.get_sftp_status() == (
        False,
        "Connection timed out (upload.appleschoolcontent.com:22).",
    )


def test_refresh_status_without_connection_marks_credentials_available(controller, monkeypatch: pytest.MonkeyPatch):
    controller._settings["sftp_username"] = "upload-user"
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "secret")

    controller._refresh_sftp_status(check_connection=False)

    assert controller.get_sftp_status() == (True, "SFTP credentials available.")


def test_reload_settings_recomputes_status_and_refreshes_page_state(controller, monkeypatch: pytest.MonkeyPatch):
    diff_page = _PageDouble()
    settings_page = _PageDouble()
    controller._diff_page = diff_page
    controller._settings_page = settings_page

    monkeypatch.setattr(ac_module.SettingsStore, "load", lambda: {"sftp_username": "upload-user"})
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "secret")
    monkeypatch.setattr(
        ac_module,
        "check_sftp_connection",
        lambda _username, _password: (True, "Connected to upload.appleschoolcontent.com:22 as 'upload-user'."),
    )

    controller.reload_settings()

    assert controller.get_sftp_status() == (
        True,
        "Connected to upload.appleschoolcontent.com:22 as 'upload-user'.",
    )
    assert diff_page.calls[-1] == (True, "Connected to upload.appleschoolcontent.com:22 as 'upload-user'.")
    assert settings_page.calls[-1] == (True, "Connected to upload.appleschoolcontent.com:22 as 'upload-user'.")


def test_save_credentials_clears_when_username_blank(controller):
    diff_page = _PageDouble()
    settings_page = _PageDouble()
    controller._diff_page = diff_page
    controller._settings_page = settings_page

    ok, message = controller.save_sftp_credentials("old-user", "   ", "")

    assert ok is True
    assert message == "SFTP credentials cleared."
    assert controller.get_sftp_status() == (False, "Missing SFTP username.")
    assert diff_page.calls[-1] == (False, "Missing SFTP username.")
    assert settings_page.calls[-1] == (False, "Missing SFTP username.")


def test_save_credentials_requires_keyring_for_configured_username(controller, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ac_module, "is_keyring_available", lambda: False)

    ok, message = controller.save_sftp_credentials("", "upload-user", "pw")

    assert ok is False
    assert message == "Secure keyring backend is not available on this system."


def test_save_credentials_username_change_without_password_requires_new_secret(
    controller,
    monkeypatch: pytest.MonkeyPatch,
):
    deleted: list[str] = []
    monkeypatch.setattr(ac_module, "delete_password", lambda username: deleted.append(username))
    monkeypatch.setattr(ac_module, "has_password", lambda _username: False)

    ok, message = controller.save_sftp_credentials("old-user", "new-user", "")

    assert ok is False
    assert message == "Enter a password when changing SFTP username."
    assert deleted == ["old-user"]


def test_save_credentials_surfaces_store_error(controller, monkeypatch: pytest.MonkeyPatch):
    def _raise(_username: str, _password: str) -> None:
        raise ac_module.CredentialError("keyring write blocked")

    monkeypatch.setattr(ac_module, "set_password", _raise)

    ok, message = controller.save_sftp_credentials("", "upload-user", "pw")

    assert ok is False
    assert message == "Could not store SFTP password securely: keyring write blocked"


def test_save_credentials_surfaces_read_error(controller, monkeypatch: pytest.MonkeyPatch):
    def _raise(_username: str) -> str:
        raise ac_module.CredentialError("keyring read blocked")

    monkeypatch.setattr(ac_module, "get_password", _raise)

    ok, message = controller.save_sftp_credentials("upload-user", "upload-user", "")

    assert ok is False
    assert message == "Could not read SFTP password: keyring read blocked"


def test_save_credentials_uses_override_password_before_keyring_fallback(
    controller,
    monkeypatch: pytest.MonkeyPatch,
):
    def _should_not_read(_username: str) -> str:
        raise AssertionError("get_password must not be called when password override is present")

    monkeypatch.setattr(ac_module, "get_password", _should_not_read)
    monkeypatch.setattr(
        ac_module,
        "check_sftp_connection",
        lambda username, _password: (True, f"Connected to upload.appleschoolcontent.com:22 as '{username}'."),
    )

    ok, message = controller.save_sftp_credentials("", "upload-user", "pw-from-ui")

    assert ok is True
    assert message == "Connected to upload.appleschoolcontent.com:22 as 'upload-user'."
    assert controller.get_sftp_status() == (True, "Connected to upload.appleschoolcontent.com:22 as 'upload-user'.")


def test_save_credentials_falls_back_to_keyring_when_override_missing(controller, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "stored-secret")
    monkeypatch.setattr(
        ac_module,
        "check_sftp_connection",
        lambda _username, _password: (False, "Authentication failed — check username and password."),
    )

    ok, message = controller.save_sftp_credentials("", "upload-user", "")

    assert ok is True
    assert message == "Authentication failed — check username and password."
    assert controller.get_sftp_status() == (False, "Authentication failed — check username and password.")


def test_save_credentials_missing_effective_password_keeps_upload_disabled(controller, monkeypatch: pytest.MonkeyPatch):
    diff_page = _PageDouble()
    settings_page = _PageDouble()
    controller._diff_page = diff_page
    controller._settings_page = settings_page
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "")

    ok, message = controller.save_sftp_credentials("", "upload-user", "")

    assert ok is True
    assert message == "Missing SFTP password."
    assert controller.get_sftp_status() == (False, "Missing SFTP password.")
    assert diff_page.calls[-1] == (False, "Missing SFTP password.")
    assert settings_page.calls[-1] == (False, "Missing SFTP password.")


def test_test_connection_rejects_blank_or_whitespace_username(controller):
    assert controller.test_sftp_connection("", "") == (False, "Missing SFTP username.")
    assert controller.test_sftp_connection("   ", "") == (False, "Missing SFTP username.")


def test_test_connection_requires_override_when_keyring_unavailable(controller, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ac_module, "is_keyring_available", lambda: False)

    ok, message = controller.test_sftp_connection("upload-user", "")

    assert ok is False
    assert message == "Secure keyring backend is unavailable and no password was provided."


def test_test_connection_prefers_override_password(controller, monkeypatch: pytest.MonkeyPatch):
    def _should_not_read(_username: str) -> str:
        raise AssertionError("get_password must not be called when password override is present")

    monkeypatch.setattr(ac_module, "get_password", _should_not_read)
    monkeypatch.setattr(ac_module, "check_sftp_connection", lambda _u, _p: (True, "Connected."))

    assert controller.test_sftp_connection("upload-user", "typed-now") == (True, "Connected.")


def test_test_connection_surfaces_credential_read_error(controller, monkeypatch: pytest.MonkeyPatch):
    def _raise(_username: str) -> str:
        raise ac_module.CredentialError("read failed")

    monkeypatch.setattr(ac_module, "get_password", _raise)

    ok, message = controller.test_sftp_connection("upload-user", "")

    assert ok is False
    assert message == "Credential error: read failed"


def test_test_connection_missing_password_after_keyring_lookup(controller, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "")

    assert controller.test_sftp_connection("upload-user", "") == (False, "Missing SFTP password.")


def test_repeated_test_clicks_keep_latest_status_after_save(controller, monkeypatch: pytest.MonkeyPatch):
    statuses = [
        (False, "Connection timed out (upload.appleschoolcontent.com:22)."),
        (False, "DNS resolution failed for upload.appleschoolcontent.com: [Errno -2] Name or service not known"),
        (True, "Connected to upload.appleschoolcontent.com:22 as 'upload-user'."),
    ]

    def _check(_username: str, _password: str):
        return statuses.pop(0)

    monkeypatch.setattr(ac_module, "check_sftp_connection", _check)

    results = [
        controller.save_sftp_credentials("", "upload-user", "pw-1"),
        controller.save_sftp_credentials("", "upload-user", "pw-2"),
        controller.save_sftp_credentials("", "upload-user", "pw-3"),
    ]

    assert results == [
        (True, "Connection timed out (upload.appleschoolcontent.com:22)."),
        (True, "DNS resolution failed for upload.appleschoolcontent.com: [Errno -2] Name or service not known"),
        (True, "Connected to upload.appleschoolcontent.com:22 as 'upload-user'."),
    ]
    assert controller.get_sftp_status() == (True, "Connected to upload.appleschoolcontent.com:22 as 'upload-user'.")


def test_save_credentials_treats_non_boolean_connection_result_as_failure(controller, monkeypatch: pytest.MonkeyPatch):
    """Defensive expectation from Q5: malformed SFTP check results must not enable upload."""

    monkeypatch.setattr(ac_module, "check_sftp_connection", lambda _u, _p: ("yes", "malformed result"))

    ok, message = controller.save_sftp_credentials("", "upload-user", "pw")

    assert ok is True
    assert message == "malformed result"
    assert controller.get_sftp_status() == (False, "malformed result")


def test_analyze_activity_log_uses_last_result_staff_ids(controller, monkeypatch: pytest.MonkeyPatch):
    controller._last_result = SimpleNamespace(
        staff=[
            {"person_id": "teacher.one"},
            {"person_id": "teacher.two"},
            {"person_id": ""},
        ]
    )

    captured: dict[str, object] = {}

    def _summary(path: str, *, generated_staff_ids=None):
        captured["path"] = path
        captured["ids"] = generated_staff_ids
        return {"path": path}

    monkeypatch.setattr(ac_module, "summarize_activity_log", _summary)
    monkeypatch.setattr(ac_module, "render_activity_log_summary", lambda _summary: "report-body")

    ok, report = controller.analyze_activity_log("activity.csv")

    assert ok is True
    assert report == "report-body"
    assert captured["path"] == "activity.csv"
    assert captured["ids"] == {"teacher.one", "teacher.two"}


def test_analyze_activity_log_surfaces_errors(controller, monkeypatch: pytest.MonkeyPatch):
    def _raise(_path: str, *, generated_staff_ids=None):
        raise ValueError("malformed csv")

    monkeypatch.setattr(ac_module, "summarize_activity_log", _raise)

    ok, report = controller.analyze_activity_log("broken.csv")

    assert ok is False
    assert report == "Could not analyze activity log: malformed csv"


def test_set_diff_baseline_from_activity_log_persists_mode_and_path(
    controller,
    monkeypatch: pytest.MonkeyPatch,
):
    saved: dict[str, object] = {}

    baseline = ac_module.GeneratorResult(
        students=[{"person_id": "stu-1"}],
        staff=[{"person_id": "teacher.one"}],
        courses=[{"course_id": "course-1"}],
        classes=[{"class_id": "class-1"}],
        rosters=[{"class_id": "class-1", "student_id": "stu-1", "roster_id": "r-1"}],
        warnings=[],
    )

    monkeypatch.setattr(ac_module, "extract_baseline_from_activity_log", lambda *_args, **_kwargs: baseline)
    monkeypatch.setattr(ac_module.SettingsStore, "save", lambda data: saved.update(data))

    ok, message = controller.set_diff_baseline_from_activity_log("C:/tmp/activity.csv")

    assert ok is True
    assert "Diff baseline set to activity log activity.csv" in message
    assert controller.get_diff_baseline_config() == ("activity_log", "C:/tmp/activity.csv")
    assert saved["diff_baseline_mode"] == "activity_log"
    assert saved["diff_baseline_path"] == "C:/tmp/activity.csv"


def test_set_diff_baseline_from_activity_log_rejects_empty_or_no_rows(
    controller,
    monkeypatch: pytest.MonkeyPatch,
):
    ok_empty, message_empty = controller.set_diff_baseline_from_activity_log("   ")
    assert ok_empty is False
    assert message_empty == "Missing activity log path."

    empty = ac_module.GeneratorResult(students=[], staff=[], courses=[], classes=[], rosters=[], warnings=[])
    monkeypatch.setattr(ac_module, "extract_baseline_from_activity_log", lambda *_args, **_kwargs: empty)

    ok_none, message_none = controller.set_diff_baseline_from_activity_log("C:/tmp/activity.csv")
    assert ok_none is False
    assert message_none == "Activity log contains no active entries to use as baseline."


def test_set_diff_baseline_from_csv_persists_mode_and_path(
    controller,
    monkeypatch: pytest.MonkeyPatch,
):
    saved: dict[str, object] = {}

    baseline = ac_module.GeneratorResult(
        students=[{"person_id": "stu-1"}],
        staff=[{"person_id": "teacher.one"}],
        courses=[{"course_id": "course-1"}],
        classes=[{"class_id": "class-1"}],
        rosters=[{"class_id": "class-1", "student_id": "stu-1", "roster_id": "r-1"}],
        warnings=[],
    )

    monkeypatch.setattr(ac_module, "load_baseline_from_csv_source", lambda _path, **_kwargs: baseline)
    monkeypatch.setattr(ac_module.SettingsStore, "save", lambda data: saved.update(data))

    ok, message = controller.set_diff_baseline_from_csv("C:/tmp/students.csv")

    assert ok is True
    assert "Diff baseline set to CSV/ZIP source students.csv" in message
    assert controller.get_diff_baseline_config() == ("csv", "C:/tmp/students.csv")
    assert saved["diff_baseline_mode"] == "csv"
    assert saved["diff_baseline_path"] == "C:/tmp/students.csv"


def test_set_diff_baseline_from_csv_rejects_empty_or_no_rows(
    controller,
    monkeypatch: pytest.MonkeyPatch,
):
    ok_empty, message_empty = controller.set_diff_baseline_from_csv("   ")
    assert ok_empty is False
    assert message_empty == "Missing CSV/ZIP baseline path."

    empty = ac_module.GeneratorResult(students=[], staff=[], courses=[], classes=[], rosters=[], warnings=[])
    monkeypatch.setattr(ac_module, "load_baseline_from_csv_source", lambda _path, **_kwargs: empty)

    ok_none, message_none = controller.set_diff_baseline_from_csv("C:/tmp/students.csv")
    assert ok_none is False
    assert message_none == "Selected CSV/ZIP baseline contains no records."


def test_clear_diff_baseline_resets_settings(controller, monkeypatch: pytest.MonkeyPatch):
    controller._settings["diff_baseline_mode"] = "activity_log"
    controller._settings["diff_baseline_path"] = "C:/tmp/activity.csv"

    saved: dict[str, object] = {}
    monkeypatch.setattr(ac_module.SettingsStore, "save", lambda data: saved.update(data))

    ok, message = controller.clear_diff_baseline()

    assert ok is True
    assert message == "Diff baseline reset to snapshot."
    assert controller.get_diff_baseline_config() == ("snapshot", "")
    assert saved["diff_baseline_mode"] == "snapshot"
    assert saved["diff_baseline_path"] == ""


def test_build_snapshot_for_diff_uses_activity_log_baseline_for_all_categories(
    controller,
    monkeypatch: pytest.MonkeyPatch,
):
    controller._settings["diff_baseline_mode"] = "activity_log"
    controller._settings["diff_baseline_path"] = "C:/tmp/activity.csv"

    baseline = ac_module.GeneratorResult(
        students=[{"person_id": "baseline-stu"}],
        staff=[{"person_id": "baseline-staff"}],
        courses=[{"course_id": "baseline-course"}],
        classes=[{"class_id": "baseline-class"}],
        rosters=[{"class_id": "baseline-class", "student_id": "baseline-stu", "roster_id": "rb"}],
        warnings=[],
    )

    monkeypatch.setattr(ac_module, "extract_baseline_from_activity_log", lambda *_args, **_kwargs: baseline)

    snapshot = ac_module.GeneratorResult(
        students=[{"person_id": "snapshot-stu"}],
        staff=[{"person_id": "snapshot-staff"}],
        courses=[{"course_id": "snapshot-course"}],
        classes=[{"class_id": "snapshot-class"}],
        rosters=[{"class_id": "snapshot-class", "student_id": "snapshot-stu", "roster_id": "rs"}],
        warnings=[],
    )

    diff_snapshot = controller._build_snapshot_for_diff(snapshot)

    assert diff_snapshot == baseline


def test_build_snapshot_for_diff_uses_csv_baseline_for_all_categories(
    controller,
    monkeypatch: pytest.MonkeyPatch,
):
    controller._settings["diff_baseline_mode"] = "csv"
    controller._settings["diff_baseline_path"] = "C:/tmp/students.csv"

    baseline = ac_module.GeneratorResult(
        students=[{"person_id": "csv-stu"}],
        staff=[{"person_id": "csv-staff"}],
        courses=[{"course_id": "csv-course"}],
        classes=[{"class_id": "csv-class"}],
        rosters=[{"class_id": "csv-class", "student_id": "csv-stu", "roster_id": "rc"}],
        warnings=[],
    )

    monkeypatch.setattr(ac_module, "load_baseline_from_csv_source", lambda _path, **_kwargs: baseline)

    snapshot = ac_module.GeneratorResult(students=[], staff=[], courses=[], classes=[], rosters=[], warnings=[])

    diff_snapshot = controller._build_snapshot_for_diff(snapshot)

    assert diff_snapshot == baseline


def test_build_snapshot_for_diff_falls_back_when_configured_baseline_fails(
    controller,
    monkeypatch: pytest.MonkeyPatch,
):
    controller._settings["diff_baseline_mode"] = "activity_log"
    controller._settings["diff_baseline_path"] = "C:/tmp/missing.csv"

    monkeypatch.setattr(
        ac_module,
        "extract_baseline_from_activity_log",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )

    snapshot = ac_module.GeneratorResult(
        students=[],
        staff=[{"person_id": "snapshot.staff"}],
        courses=[],
        classes=[],
        rosters=[],
        warnings=[],
    )

    diff_snapshot = controller._build_snapshot_for_diff(snapshot)

    assert diff_snapshot == snapshot


def test_set_diff_baseline_from_last_export_uses_first_existing_path(
    controller,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    existing = tmp_path / "students.csv"
    existing.write_text("person_id\n", encoding="utf-8")

    controller._settings["last_export_paths"] = ["C:/missing.csv", str(existing)]

    captured: dict[str, str] = {}

    def _set_from_csv(path: str):
        captured["path"] = path
        return True, "Diff baseline set to CSV/ZIP source students.csv (students=1, staff=1, courses=1, classes=1, rosters=1)."

    monkeypatch.setattr(controller, "set_diff_baseline_from_csv", _set_from_csv)

    ok, message = controller.set_diff_baseline_from_last_export()

    assert ok is True
    assert captured["path"] == str(existing)
    assert message.startswith("Diff baseline set from last export:")


def test_set_diff_baseline_from_last_export_rejects_paths_missing_on_disk(controller):
    controller._settings["last_export_paths"] = ["C:/missing-a.csv", "C:/missing-b.csv"]

    ok, message = controller.set_diff_baseline_from_last_export()

    assert ok is False
    assert message == "Configured export files were not found on disk."


def test_set_diff_baseline_from_last_export_rejects_missing_paths(controller):
    controller._settings["last_export_paths"] = []

    ok, message = controller.set_diff_baseline_from_last_export()

    assert ok is False
    assert message == "No previous export paths are configured yet."


class _DiffUploadPageDouble:
    def __init__(self) -> None:
        self.reset_calls = 0

    def get_approved_records(self) -> dict[str, list[dict]]:
        return {
            "students": [],
            "staff": [],
            "courses": [],
            "classes": [],
            "rosters": [],
        }

    def reset(self) -> None:
        self.reset_calls += 1


class _ButtonDouble:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:  # noqa: N802 - mirrors Qt API casing
        self.text = text


class _MessageBoxDouble:
    next_results: list[bool] = []
    shown: list[tuple[str, str]] = []

    def __init__(self, title: str, text: str, _parent) -> None:
        self.title = title
        self.text = text
        self.yesButton = _ButtonDouble()
        self.cancelButton = _ButtonDouble()
        self.__class__.shown.append((title, text))

    def exec(self) -> bool:
        if self.__class__.next_results:
            return self.__class__.next_results.pop(0)
        return True


def test_export_upload_attempts_backup_before_upload_and_saves_snapshot(controller, monkeypatch: pytest.MonkeyPatch):
    import asm_generator.writer as writer_module

    controller._sftp_ready = True
    controller._settings["sftp_username"] = "upload-user"
    controller._diff_page = _DiffUploadPageDouble()
    controller._last_result = SimpleNamespace(warnings=["w1"])

    call_order: list[str] = []

    monkeypatch.setattr(ac_module, "MessageBox", _MessageBoxDouble)
    _MessageBoxDouble.next_results = []
    _MessageBoxDouble.shown = []
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "pw")

    def _write(_result, path: str) -> None:
        call_order.append("write")
        Path(path).write_text("zip")

    monkeypatch.setattr(writer_module, "write_to_zip", _write)
    monkeypatch.setattr(ac_module, "create_backup", lambda _path: call_order.append("backup"))
    monkeypatch.setattr(
        ac_module,
        "upload_file",
        lambda _path, username, password: (call_order.append("upload") or f"{username}:{password}"),
    )
    monkeypatch.setattr(ac_module, "save_snapshot", lambda _result: call_order.append("snapshot"))

    controller.export_zip_and_upload()

    assert call_order == ["write", "backup", "upload", "snapshot"]
    assert controller._diff_page.reset_calls == 1
    assert _MessageBoxDouble.shown[-1][0] == "Upload Successful"


def test_export_upload_backup_failure_cancel_aborts_before_upload(controller, monkeypatch: pytest.MonkeyPatch):
    import asm_generator.writer as writer_module

    controller._sftp_ready = True
    controller._settings["sftp_username"] = "upload-user"
    controller._diff_page = _DiffUploadPageDouble()

    called = {"upload": 0, "snapshot": 0}

    monkeypatch.setattr(ac_module, "MessageBox", _MessageBoxDouble)
    _MessageBoxDouble.next_results = [False]
    _MessageBoxDouble.shown = []
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "pw")
    monkeypatch.setattr(writer_module, "write_to_zip", lambda _result, path: Path(path).write_text("zip"))

    def _backup_fail(_path) -> None:
        raise RuntimeError("backup copy failed: disk full")

    monkeypatch.setattr(ac_module, "create_backup", _backup_fail)
    monkeypatch.setattr(
        ac_module,
        "upload_file",
        lambda _path, username, password: called.__setitem__("upload", called["upload"] + 1),
    )
    monkeypatch.setattr(
        ac_module,
        "save_snapshot",
        lambda _result: called.__setitem__("snapshot", called["snapshot"] + 1),
    )

    controller.export_zip_and_upload()

    assert called == {"upload": 0, "snapshot": 0}
    assert controller._diff_page.reset_calls == 0
    assert _MessageBoxDouble.shown[-1][0] == "Backup Failed"
    assert "backup copy failed: disk full" in _MessageBoxDouble.shown[-1][1]
    assert "Proceed without backup?" in _MessageBoxDouble.shown[-1][1]


def test_export_upload_backup_failure_proceed_continues_to_upload(controller, monkeypatch: pytest.MonkeyPatch):
    import asm_generator.writer as writer_module

    controller._sftp_ready = True
    controller._settings["sftp_username"] = "upload-user"
    controller._diff_page = _DiffUploadPageDouble()

    called = {"upload": 0, "snapshot": 0}

    monkeypatch.setattr(ac_module, "MessageBox", _MessageBoxDouble)
    _MessageBoxDouble.next_results = [True]
    _MessageBoxDouble.shown = []
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "pw")
    monkeypatch.setattr(writer_module, "write_to_zip", lambda _result, path: Path(path).write_text("zip"))

    def _backup_fail(_path) -> None:
        raise ValueError("unexpected backup adapter response")

    monkeypatch.setattr(ac_module, "create_backup", _backup_fail)
    monkeypatch.setattr(
        ac_module,
        "upload_file",
        lambda _path, username, password: called.__setitem__("upload", called["upload"] + 1) or "remote.zip",
    )
    monkeypatch.setattr(
        ac_module,
        "save_snapshot",
        lambda _result: called.__setitem__("snapshot", called["snapshot"] + 1),
    )

    controller.export_zip_and_upload()

    assert called == {"upload": 1, "snapshot": 1}
    assert controller._diff_page.reset_calls == 1
    assert [title for title, _text in _MessageBoxDouble.shown] == ["Backup Failed", "Upload Successful"]


def test_export_upload_missing_credentials_blocks_before_backup_and_upload(
    controller,
    monkeypatch: pytest.MonkeyPatch,
):
    controller._sftp_ready = True
    controller._settings["sftp_username"] = ""
    controller._diff_page = _DiffUploadPageDouble()

    called = {"backup": 0, "upload": 0}

    monkeypatch.setattr(ac_module, "MessageBox", _MessageBoxDouble)
    _MessageBoxDouble.next_results = []
    _MessageBoxDouble.shown = []
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "")
    monkeypatch.setattr(
        ac_module,
        "create_backup",
        lambda _path: called.__setitem__("backup", called["backup"] + 1),
    )
    monkeypatch.setattr(
        ac_module,
        "upload_file",
        lambda _path, username, password: called.__setitem__("upload", called["upload"] + 1),
    )

    controller.export_zip_and_upload()

    assert called == {"backup": 0, "upload": 0}
    assert _MessageBoxDouble.shown[-1][0] == "Missing Credentials"


def test_export_upload_failure_after_successful_backup_keeps_snapshot_unsaved(
    controller,
    monkeypatch: pytest.MonkeyPatch,
):
    import asm_generator.writer as writer_module

    controller._sftp_ready = True
    controller._settings["sftp_username"] = "upload-user"
    controller._diff_page = _DiffUploadPageDouble()

    called = {"snapshot": 0}

    monkeypatch.setattr(ac_module, "MessageBox", _MessageBoxDouble)
    _MessageBoxDouble.next_results = []
    _MessageBoxDouble.shown = []
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "pw")
    monkeypatch.setattr(writer_module, "write_to_zip", lambda _result, path: Path(path).write_text("zip"))
    monkeypatch.setattr(ac_module, "create_backup", lambda _path: None)

    def _upload_fail(_path, username: str, password: str) -> str:
        raise TimeoutError(f"SFTP upload timed out for {username}.")

    monkeypatch.setattr(ac_module, "upload_file", _upload_fail)
    monkeypatch.setattr(
        ac_module,
        "save_snapshot",
        lambda _result: called.__setitem__("snapshot", called["snapshot"] + 1),
    )

    controller.export_zip_and_upload()

    assert called == {"snapshot": 0}
    assert controller._diff_page.reset_calls == 0
    assert _MessageBoxDouble.shown[-1][0] == "Upload Failed"
    assert "SFTP upload timed out" in _MessageBoxDouble.shown[-1][1]


def test_export_upload_interruption_retry_then_success_preserves_backup_once(
    controller,
    monkeypatch: pytest.MonkeyPatch,
):
    import asm_generator.writer as writer_module

    controller._sftp_ready = True
    controller._settings["sftp_username"] = "upload-user"
    controller._diff_page = _DiffUploadPageDouble()

    events: list[str] = []
    attempts = {"upload": 0, "snapshot": 0}

    monkeypatch.setattr(ac_module, "MessageBox", _MessageBoxDouble)
    _MessageBoxDouble.shown = []
    _MessageBoxDouble.next_results = [True]  # Retry after first interruption
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "pw")
    monkeypatch.setattr(
        writer_module,
        "write_to_zip",
        lambda _result, path: (events.append("write"), Path(path).write_text("zip")),
    )
    monkeypatch.setattr(ac_module, "create_backup", lambda _path: events.append("backup"))

    def _upload_retry_then_success(_path, username: str, password: str) -> str:
        assert username == "upload-user"
        assert password == "pw"
        attempts["upload"] += 1
        events.append(f"upload-{attempts['upload']}")
        if attempts["upload"] == 1:
            raise RuntimeError("Upload interrupted — connection timed out during transfer.")
        return "remote.zip"

    monkeypatch.setattr(ac_module, "upload_file", _upload_retry_then_success)
    monkeypatch.setattr(
        ac_module,
        "save_snapshot",
        lambda _result: (events.append("snapshot"), attempts.__setitem__("snapshot", attempts["snapshot"] + 1)),
    )

    controller.export_zip_and_upload()

    assert attempts == {"upload": 2, "snapshot": 1}
    assert events == ["write", "backup", "upload-1", "upload-2", "snapshot"]
    assert controller._diff_page.reset_calls == 1
    titles = [title for title, _ in _MessageBoxDouble.shown]
    assert titles == ["Upload Interrupted", "Upload Successful"]
    assert "Retry" in _MessageBoxDouble.shown[0][1]
    assert "Cancel" in _MessageBoxDouble.shown[0][1]


def test_export_upload_interruption_cancel_aborts_without_snapshot_or_reset(
    controller,
    monkeypatch: pytest.MonkeyPatch,
):
    import asm_generator.writer as writer_module

    controller._sftp_ready = True
    controller._settings["sftp_username"] = "upload-user"
    controller._diff_page = _DiffUploadPageDouble()

    called = {"backup": 0, "upload": 0, "snapshot": 0}

    monkeypatch.setattr(ac_module, "MessageBox", _MessageBoxDouble)
    _MessageBoxDouble.shown = []
    _MessageBoxDouble.next_results = [False]  # Cancel from retry dialog
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "pw")
    monkeypatch.setattr(writer_module, "write_to_zip", lambda _result, path: Path(path).write_text("zip"))
    monkeypatch.setattr(
        ac_module,
        "create_backup",
        lambda _path: called.__setitem__("backup", called["backup"] + 1),
    )

    def _upload_fail_once(_path, username: str, password: str) -> str:
        assert username == "upload-user"
        assert password == "pw"
        called["upload"] += 1
        raise RuntimeError("Upload interrupted — connection was lost during transfer.")

    monkeypatch.setattr(ac_module, "upload_file", _upload_fail_once)
    monkeypatch.setattr(
        ac_module,
        "save_snapshot",
        lambda _result: called.__setitem__("snapshot", called["snapshot"] + 1),
    )

    controller.export_zip_and_upload()

    assert called == {"backup": 1, "upload": 1, "snapshot": 0}
    assert controller._diff_page.reset_calls == 0
    assert _MessageBoxDouble.shown[-1][0] == "Upload Interrupted"
    assert "Retry" in _MessageBoxDouble.shown[-1][1]
    assert "Cancel" in _MessageBoxDouble.shown[-1][1]


def test_export_upload_auth_failure_uses_credentials_message_branch(
    controller,
    monkeypatch: pytest.MonkeyPatch,
):
    import asm_generator.writer as writer_module

    controller._sftp_ready = True
    controller._settings["sftp_username"] = "upload-user"
    controller._diff_page = _DiffUploadPageDouble()

    called = {"backup": 0, "upload": 0, "snapshot": 0}

    monkeypatch.setattr(ac_module, "MessageBox", _MessageBoxDouble)
    _MessageBoxDouble.shown = []
    _MessageBoxDouble.next_results = [False]  # Cancel after auth guidance
    monkeypatch.setattr(ac_module, "get_password", lambda _username: "pw")
    monkeypatch.setattr(writer_module, "write_to_zip", lambda _result, path: Path(path).write_text("zip"))
    monkeypatch.setattr(
        ac_module,
        "create_backup",
        lambda _path: called.__setitem__("backup", called["backup"] + 1),
    )

    def _upload_auth_fail(_path, username: str, password: str) -> str:
        assert username == "upload-user"
        assert password == "pw"
        called["upload"] += 1
        raise RuntimeError("Authentication failed — check username and password.")

    monkeypatch.setattr(ac_module, "upload_file", _upload_auth_fail)
    monkeypatch.setattr(
        ac_module,
        "save_snapshot",
        lambda _result: called.__setitem__("snapshot", called["snapshot"] + 1),
    )

    controller.export_zip_and_upload()

    assert called == {"backup": 1, "upload": 1, "snapshot": 0}
    assert controller._diff_page.reset_calls == 0
    assert _MessageBoxDouble.shown[-1][0] == "Upload Authentication Failed"
    assert "check SFTP username/password" in _MessageBoxDouble.shown[-1][1]
    assert "Retry" in _MessageBoxDouble.shown[-1][1]
