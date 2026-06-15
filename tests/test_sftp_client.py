"""Robustness tests for SFTP transport adapter contracts."""

from __future__ import annotations

import builtins
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import sftp_client


class _FakeTransport:
    def __init__(self, sock) -> None:
        self.sock = sock
        self.closed = False
        self.connect_calls: list[tuple[str, str]] = []
        self.connect_side_effect = None

    def connect(self, *, username: str, password: str) -> None:
        self.connect_calls.append((username, password))
        if self.connect_side_effect is not None:
            raise self.connect_side_effect

    def close(self) -> None:
        self.closed = True


class _FakeSFTP:
    def __init__(self) -> None:
        self.put_calls: list[tuple[str, str]] = []
        self.closed = False
        self.put_side_effect = None

    def put(self, local: str, remote: str) -> None:
        self.put_calls.append((local, remote))
        if self.put_side_effect is not None:
            raise self.put_side_effect

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_paramiko(monkeypatch: pytest.MonkeyPatch):
    transport_holder: dict[str, _FakeTransport] = {}
    sftp_holder: dict[str, _FakeSFTP] = {}

    class AuthenticationException(Exception):
        pass

    def _make_transport(sock):
        transport = _FakeTransport(sock)
        transport_holder["instance"] = transport
        return transport

    def _from_transport(_transport):
        sftp = _FakeSFTP()
        sftp_holder["instance"] = sftp
        return sftp

    fake_module = SimpleNamespace(
        AuthenticationException=AuthenticationException,
        Transport=_make_transport,
        SFTPClient=SimpleNamespace(from_transport=_from_transport),
    )
    monkeypatch.setitem(sys.modules, "paramiko", fake_module)
    return fake_module, transport_holder, sftp_holder


def _force_import_error(monkeypatch: pytest.MonkeyPatch, module_name: str) -> None:
    real_import = builtins.__import__

    def _patched(name, globals=None, locals=None, fromlist=(), level=0):
        if name == module_name or name.startswith(f"{module_name}."):
            raise ImportError(f"forced missing module: {module_name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _patched)


def test_check_connection_returns_unavailable_when_paramiko_missing(monkeypatch: pytest.MonkeyPatch):
    _force_import_error(monkeypatch, "paramiko")

    ok, message = sftp_client.check_connection("user", "pw")

    assert ok is False
    assert message == "paramiko is not installed; SFTP upload is unavailable."


def test_check_connection_success_returns_connected_message(
    monkeypatch: pytest.MonkeyPatch,
    fake_paramiko,
):
    _, transport_holder, _ = fake_paramiko
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: object())

    ok, message = sftp_client.check_connection("upload-user", "pw")

    assert ok is True
    assert message == "Connected to upload.appleschoolcontent.com:22 as 'upload-user'."
    assert transport_holder["instance"].connect_calls == [("upload-user", "pw")]
    assert transport_holder["instance"].closed is True


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            socket.timeout("too slow"),
            "Connection timed out (upload.appleschoolcontent.com:22).",
        ),
        (
            socket.gaierror(-2, "Name or service not known"),
            "DNS resolution failed for upload.appleschoolcontent.com: [Errno -2] Name or service not known",
        ),
        (
            RuntimeError("boom"),
            "Connection error: boom",
        ),
    ],
)
def test_check_connection_maps_socket_and_generic_errors(
    monkeypatch: pytest.MonkeyPatch,
    fake_paramiko,
    error: Exception,
    expected: str,
):
    _, _transport_holder, _ = fake_paramiko

    def _raise(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(socket, "create_connection", _raise)

    ok, message = sftp_client.check_connection("upload-user", "pw")

    assert ok is False
    assert message == expected


def test_check_connection_maps_auth_failure(monkeypatch: pytest.MonkeyPatch, fake_paramiko):
    fake_module, transport_holder, _ = fake_paramiko
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: object())

    transport = _FakeTransport(object())
    transport.connect_side_effect = fake_module.AuthenticationException("bad creds")
    transport_holder["instance"] = transport
    fake_module.Transport = lambda _sock: transport

    ok, message = sftp_client.check_connection("upload-user", "bad")

    assert ok is False
    assert message == "Authentication failed — check username and password."
    assert transport.closed is True


def test_check_connection_repeated_auth_failures_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    fake_paramiko,
):
    fake_module, _transport_holder, _ = fake_paramiko
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: object())

    def _make_auth_fail_transport(_sock):
        transport = _FakeTransport(_sock)
        transport.connect_side_effect = fake_module.AuthenticationException("always fail")
        return transport

    fake_module.Transport = _make_auth_fail_transport

    for _ in range(10):
        ok, message = sftp_client.check_connection("upload-user", "bad")
        assert ok is False
        assert message == "Authentication failed — check username and password."


def test_upload_file_success_uploads_and_returns_remote_name(
    monkeypatch: pytest.MonkeyPatch,
    fake_paramiko,
    tmp_path: Path,
):
    _, transport_holder, sftp_holder = fake_paramiko
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: object())

    local = tmp_path / "asm_export.zip"
    local.write_text("zip")

    remote_name = sftp_client.upload_file(local, username="upload-user", password="pw")

    assert remote_name == "asm_export.zip"
    assert transport_holder["instance"].closed is True
    assert sftp_holder["instance"].closed is True
    assert sftp_holder["instance"].put_calls == [(str(local), "asm_export.zip")]


def test_upload_file_applies_longer_timeout_for_transfer_phase(
    monkeypatch: pytest.MonkeyPatch,
    fake_paramiko,
    tmp_path: Path,
):
    _, _transport_holder, _sftp_holder = fake_paramiko

    class _SocketDouble:
        def __init__(self) -> None:
            self.timeout_values: list[float] = []

        def settimeout(self, value: float) -> None:
            self.timeout_values.append(value)

    socket_double = _SocketDouble()
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: socket_double)

    local = tmp_path / "asm_export.zip"
    local.write_text("zip")

    sftp_client.upload_file(local, username="upload-user", password="pw")

    assert socket_double.timeout_values == [sftp_client._UPLOAD_IO_TIMEOUT]


def test_upload_file_raises_runtime_error_when_paramiko_missing(monkeypatch: pytest.MonkeyPatch):
    _force_import_error(monkeypatch, "paramiko")

    with pytest.raises(RuntimeError, match="paramiko is not installed; SFTP upload is unavailable."):
        sftp_client.upload_file("missing.zip", username="upload-user", password="pw")


def test_upload_file_maps_auth_timeout_and_dns_errors(
    monkeypatch: pytest.MonkeyPatch,
    fake_paramiko,
):
    fake_module, _transport_holder, _sftp_holder = fake_paramiko
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: object())

    transport = _FakeTransport(object())
    transport.connect_side_effect = fake_module.AuthenticationException("bad creds")
    fake_module.Transport = lambda _sock: transport

    with pytest.raises(RuntimeError, match="Authentication failed — check username and password."):
        sftp_client.upload_file("asm_export.zip", username="upload-user", password="bad")

    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: (_ for _ in ()).throw(socket.timeout("late")))
    with pytest.raises(RuntimeError, match=r"Connection timed out \(upload\.appleschoolcontent\.com:22\)\."):
        sftp_client.upload_file("asm_export.zip", username="upload-user", password="pw")

    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(socket.gaierror(-2, "Name or service not known")),
    )
    with pytest.raises(RuntimeError, match=r"DNS resolution failed for upload\.appleschoolcontent\.com:"):
        sftp_client.upload_file("asm_export.zip", username="upload-user", password="pw")


def test_upload_file_invalid_local_path_bubbles_as_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    fake_paramiko,
):
    fake_module, transport_holder, sftp_holder = fake_paramiko
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: object())

    transport = _FakeTransport(object())
    transport_holder["instance"] = transport
    fake_module.Transport = lambda _sock: transport

    sftp = _FakeSFTP()
    sftp.put_side_effect = FileNotFoundError("No such file or directory")
    sftp_holder["instance"] = sftp
    fake_module.SFTPClient = SimpleNamespace(from_transport=lambda _transport: sftp)

    with pytest.raises(RuntimeError, match="No such file or directory"):
        sftp_client.upload_file("does-not-exist.zip", username="upload-user", password="pw")

    assert transport.closed is True
    assert sftp.closed is True


@pytest.mark.parametrize(
    ("upload_error", "expected_message"),
    [
        (
            TimeoutError("socket stalled during transfer"),
            "Upload interrupted — connection timed out during transfer.",
        ),
        (
            RuntimeError("Connection reset by peer during put"),
            "Upload interrupted — connection was lost during transfer.",
        ),
        (
            OSError("EOF during SFTP packet read"),
            "Upload interrupted — transfer ended unexpectedly.",
        ),
    ],
)
def test_upload_file_normalizes_interruption_signatures(
    monkeypatch: pytest.MonkeyPatch,
    fake_paramiko,
    upload_error: Exception,
    expected_message: str,
):
    fake_module, transport_holder, sftp_holder = fake_paramiko
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: object())

    transport = _FakeTransport(object())
    transport_holder["instance"] = transport
    fake_module.Transport = lambda _sock: transport

    sftp = _FakeSFTP()
    sftp.put_side_effect = upload_error
    sftp_holder["instance"] = sftp
    fake_module.SFTPClient = SimpleNamespace(from_transport=lambda _transport: sftp)

    with pytest.raises(RuntimeError) as raised:
        sftp_client.upload_file("asm_export.zip", username="upload-user", password="pw")

    assert str(raised.value) == expected_message
    assert transport.closed is True
    assert sftp.closed is True


class _WeirdUploadFailure(Exception):
    pass


@pytest.mark.parametrize(
    "upload_error",
    [
        RuntimeError(""),
        RuntimeError("unknown transport adapter explosion"),
        _WeirdUploadFailure("opaque failure marker"),
    ],
)
def test_upload_file_falls_back_to_generic_interruption_message_for_unknown_failures(
    monkeypatch: pytest.MonkeyPatch,
    fake_paramiko,
    upload_error: Exception,
):
    fake_module, transport_holder, sftp_holder = fake_paramiko
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: object())

    transport = _FakeTransport(object())
    transport_holder["instance"] = transport
    fake_module.Transport = lambda _sock: transport

    sftp = _FakeSFTP()
    sftp.put_side_effect = upload_error
    sftp_holder["instance"] = sftp
    fake_module.SFTPClient = SimpleNamespace(from_transport=lambda _transport: sftp)

    with pytest.raises(RuntimeError) as raised:
        sftp_client.upload_file("asm_export.zip", username="upload-user", password="pw")

    assert str(raised.value) == "Upload interrupted — unknown transfer error."
    assert transport.closed is True
    assert sftp.closed is True
