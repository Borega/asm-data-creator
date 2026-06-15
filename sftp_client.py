"""SFTP client for uploading ASM ZIP files to Apple School Content.

Public API
----------
check_connection(username, password) -> tuple[bool, str]
    Attempt a connection to the ASM SFTP host and return (success, message).

upload_file(local_path, username, password) -> str
    Upload *local_path* to the SFTP server and return the remote filename.
"""
from __future__ import annotations

import socket
from pathlib import Path

SFTP_HOST = "upload.appleschoolcontent.com"
SFTP_PORT = 22
_HOST = SFTP_HOST
_PORT = SFTP_PORT
_CONNECT_TIMEOUT = 15  # seconds (TCP connect)
_UPLOAD_IO_TIMEOUT = 120  # seconds (SSH auth + SFTP transfer)


def _set_socket_timeout(sock: object, timeout_seconds: float) -> None:
    """Best-effort socket timeout setter used for post-connect upload I/O."""
    setter = getattr(sock, "settimeout", None)
    if setter is None:
        return
    try:
        setter(timeout_seconds)
    except Exception:  # noqa: BLE001
        # Keep upload flow resilient if a custom socket-like object refuses timeout changes.
        pass


def _normalize_upload_transfer_error(exc: Exception) -> str:
    """Map low-level transport failures to stable user-safe interruption copy."""
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "Upload interrupted — connection timed out during transfer."

    message = str(exc or "").strip()
    lowered = message.lower()

    if any(token in lowered for token in ("connection reset", "connection lost", "broken pipe", "connection aborted")):
        return "Upload interrupted — connection was lost during transfer."

    if any(token in lowered for token in ("eof", "end of file", "channel closed", "partial", "incomplete")):
        return "Upload interrupted — transfer ended unexpectedly."

    return "Upload interrupted — unknown transfer error."


def check_connection(username: str, password: str) -> tuple[bool, str]:
    """Try to authenticate to the ASM SFTP server.

    Returns a (success, human-readable message) tuple.  Never raises.
    """
    try:
        import paramiko  # type: ignore[import]
    except ImportError:
        return False, "paramiko is not installed; SFTP upload is unavailable."

    transport: paramiko.Transport | None = None
    try:
        sock = socket.create_connection((_HOST, _PORT), timeout=_CONNECT_TIMEOUT)
        transport = paramiko.Transport(sock)
        transport.connect(username=username, password=password)
        return True, f"Connected to {_HOST}:{_PORT} as '{username}'."
    except paramiko.AuthenticationException:
        return False, "Authentication failed — check username and password."
    except TimeoutError:
        return False, f"Connection timed out ({_HOST}:{_PORT})."
    except socket.gaierror as exc:
        return False, f"DNS resolution failed for {_HOST}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Connection error: {exc}"
    finally:
        if transport is not None:
            try:
                transport.close()
            except Exception:  # noqa: BLE001
                pass


def upload_file(
    local_path: Path | str,
    *,
    username: str,
    password: str,
) -> str:
    """Upload *local_path* to the ASM SFTP server.

    Parameters
    ----------
    local_path:
        Path of the local ZIP file to upload.
    username:
        ASM SFTP username.
    password:
        Corresponding password.

    Returns
    -------
    str
        The remote filename (not the full path) as placed on the server.

    Raises
    ------
    RuntimeError
        On any connection, authentication, or transfer failure.
    """
    try:
        import paramiko  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "paramiko is not installed; SFTP upload is unavailable."
        ) from exc

    local_path = Path(local_path)
    remote_name = local_path.name

    transport: paramiko.Transport | None = None
    sftp: paramiko.SFTPClient | None = None
    try:
        sock = socket.create_connection((_HOST, _PORT), timeout=_CONNECT_TIMEOUT)
        _set_socket_timeout(sock, _UPLOAD_IO_TIMEOUT)
        transport = paramiko.Transport(sock)
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        assert sftp is not None  # noqa: S101

        try:
            sftp.put(str(local_path), remote_name)
        except FileNotFoundError as exc:
            raise RuntimeError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(_normalize_upload_transfer_error(exc)) from exc

        return remote_name
    except paramiko.AuthenticationException as exc:
        raise RuntimeError("Authentication failed — check username and password.") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"Connection timed out ({_HOST}:{_PORT}).") from exc
    except socket.gaierror as exc:
        raise RuntimeError(f"DNS resolution failed for {_HOST}: {exc}") from exc
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(str(exc)) from exc
    finally:
        if sftp is not None:
            try:
                sftp.close()
            except Exception:  # noqa: BLE001
                pass
        if transport is not None:
            try:
                transport.close()
            except Exception:  # noqa: BLE001
                pass
