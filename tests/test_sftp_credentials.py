"""Robustness tests for keyring-backed SFTP credential adapter."""

from __future__ import annotations

import builtins
import sys
from types import ModuleType

import pytest

import sftp_credentials as creds


class _FakeKeyring:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}
        self.set_side_effect = None
        self.get_side_effect = None
        self.delete_side_effect = None

    def set_password(self, service: str, username: str, password: str) -> None:
        if self.set_side_effect is not None:
            raise self.set_side_effect
        self.store[(service, username)] = password

    def get_password(self, service: str, username: str):
        if self.get_side_effect is not None:
            raise self.get_side_effect
        return self.store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        if self.delete_side_effect is not None:
            raise self.delete_side_effect
        self.store.pop((service, username), None)


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch):
    backend = _FakeKeyring()
    keyring_module = ModuleType("keyring")
    keyring_module.set_password = backend.set_password
    keyring_module.get_password = backend.get_password
    keyring_module.delete_password = backend.delete_password

    keyring_errors = ModuleType("keyring.errors")

    monkeypatch.setitem(sys.modules, "keyring", keyring_module)
    monkeypatch.setitem(sys.modules, "keyring.errors", keyring_errors)
    return backend


def _force_import_error(monkeypatch: pytest.MonkeyPatch, module_name: str) -> None:
    real_import = builtins.__import__

    def _patched(name, globals=None, locals=None, fromlist=(), level=0):
        if name == module_name or name.startswith(f"{module_name}."):
            raise ImportError(f"forced missing module: {module_name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _patched)


def test_is_keyring_available_returns_true_on_probe_roundtrip(fake_keyring):
    assert creds.is_keyring_available() is True


def test_is_keyring_available_returns_false_on_backend_error(fake_keyring):
    fake_keyring.set_side_effect = RuntimeError("backend unavailable")

    assert creds.is_keyring_available() is False


def test_is_keyring_available_returns_false_when_keyring_missing(monkeypatch: pytest.MonkeyPatch):
    _force_import_error(monkeypatch, "keyring")

    assert creds.is_keyring_available() is False


def test_get_password_returns_value_or_empty_string(fake_keyring):
    fake_keyring.store[("asm-generator-sftp", "user")] = "secret"

    assert creds.get_password("user") == "secret"
    assert creds.get_password("missing") == ""


def test_get_password_wraps_backend_exception(fake_keyring):
    fake_keyring.get_side_effect = RuntimeError("backend read failed")

    with pytest.raises(creds.CredentialError, match="Could not read password from keyring: backend read failed"):
        creds.get_password("user")


def test_get_password_wraps_import_error(monkeypatch: pytest.MonkeyPatch):
    _force_import_error(monkeypatch, "keyring")

    with pytest.raises(creds.CredentialError, match="Could not read password from keyring"):
        creds.get_password("user")


def test_set_password_stores_secret_and_wraps_errors(fake_keyring):
    creds.set_password("user", "pw")
    assert fake_keyring.store[("asm-generator-sftp", "user")] == "pw"

    fake_keyring.set_side_effect = RuntimeError("backend write blocked")
    with pytest.raises(creds.CredentialError, match="Could not save password to keyring: backend write blocked"):
        creds.set_password("user", "pw2")


def test_set_password_wraps_import_error(monkeypatch: pytest.MonkeyPatch):
    _force_import_error(monkeypatch, "keyring")

    with pytest.raises(creds.CredentialError, match="Could not save password to keyring"):
        creds.set_password("user", "pw")


def test_delete_password_is_noop_for_missing_and_backend_errors(fake_keyring):
    creds.delete_password("missing")

    fake_keyring.delete_side_effect = RuntimeError("delete failed")
    creds.delete_password("user")  # no raise by contract


def test_has_password_semantics_for_present_empty_and_errors(fake_keyring):
    fake_keyring.store[("asm-generator-sftp", "user")] = "secret"
    fake_keyring.store[("asm-generator-sftp", "empty")]= ""

    assert creds.has_password("user") is True
    assert creds.has_password("empty") is False
    assert creds.has_password("missing") is False

    fake_keyring.get_side_effect = RuntimeError("backend read failed")
    assert creds.has_password("user") is False
