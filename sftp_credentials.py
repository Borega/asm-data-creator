"""Keyring-backed SFTP credential storage.

Wraps the ``keyring`` library so the rest of the application never touches
keyring directly.  All functions raise :exc:`CredentialError` instead of
propagating raw keyring exceptions.
"""
from __future__ import annotations

_KEYRING_SERVICE = "asm-generator-sftp"


class CredentialError(Exception):
    """Raised when a credential operation fails."""


def is_keyring_available() -> bool:
    """Return True if a functional keyring backend is available."""
    try:
        import keyring

        # A dummy round-trip with a throw-away key is the only reliable way
        # to detect a broken / null backend without triggering warnings.
        _probe_service = "asm-generator-probe"
        _probe_user = "__probe__"
        keyring.set_password(_probe_service, _probe_user, "1")
        val = keyring.get_password(_probe_service, _probe_user)
        keyring.delete_password(_probe_service, _probe_user)
        return val == "1"
    except Exception:  # noqa: BLE001
        return False


def get_password(username: str) -> str:
    """Return the stored password for *username*, or an empty string if absent."""
    try:
        import keyring

        result = keyring.get_password(_KEYRING_SERVICE, username)
        return result or ""
    except Exception as exc:  # noqa: BLE001
        raise CredentialError(f"Could not read password from keyring: {exc}") from exc


def set_password(username: str, password: str) -> None:
    """Store *password* for *username* in the system keyring."""
    try:
        import keyring

        keyring.set_password(_KEYRING_SERVICE, username, password)
    except Exception as exc:  # noqa: BLE001
        raise CredentialError(f"Could not save password to keyring: {exc}") from exc


def delete_password(username: str) -> None:
    """Remove the stored password for *username* (no-op if not present)."""
    try:
        import keyring

        keyring.delete_password(_KEYRING_SERVICE, username)
    except Exception:  # noqa: BLE001
        # Ignore "not found" errors — the credential either didn't exist or
        # the backend doesn't support deletion.
        pass


def has_password(username: str) -> bool:
    """Return True if a non-empty password is stored for *username*."""
    try:
        return bool(get_password(username))
    except CredentialError:
        return False
