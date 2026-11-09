"""Tests for auth.py — credential read/write + service builders."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    import pytest_mock

from hermes_google.core import auth as auth_module
from hermes_google.core.auth import (
    SCOPES,
    AuthError,
    build_services,
    load_credentials,
    save_credentials,
    stored_scopes,
)


class _FakeCreds:
    """Minimal stand-in for google.oauth2.credentials.Credentials."""

    def __init__(self, token: str = "t", refresh_token: str = "r", expired: bool = False):
        self.token = token
        self.refresh_token = refresh_token
        self.expired = expired
        self.valid = not expired
        self._json = {
            "token": token,
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "cid",
            "client_secret": "csec",
            "scopes": list(SCOPES),
        }

    def refresh(self, _request) -> None:
        self.token = self.token + "-refreshed"
        self._json["token"] = self.token
        self.expired = False
        self.valid = True

    def to_json(self) -> str:
        return json.dumps(self._json)


def test_save_credentials_writes_with_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    creds = _FakeCreds()
    save_credentials(creds, path)  # type: ignore[arg-type]
    assert path.exists()
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600
    data = json.loads(path.read_text())
    assert data["refresh_token"] == "r"


def test_load_credentials_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(AuthError, match="credentials not found"):
        load_credentials(tmp_path / "nope.json")


def test_load_credentials_refreshes_when_expired(
    tmp_path: Path, mocker: pytest_mock.MockerFixture
) -> None:
    path = tmp_path / "credentials.json"
    saved = _FakeCreds(expired=True)
    save_credentials(saved, path)  # type: ignore[arg-type]

    def _from_file(file_path, scopes):  # noqa: ARG001
        return _FakeCreds(token="loaded", expired=True)

    mocker.patch.object(
        auth_module.Credentials, "from_authorized_user_file", side_effect=_from_file
    )
    mocker.patch.object(auth_module, "Request", lambda: object())

    creds = load_credentials(path)
    assert creds.valid is True
    assert "refreshed" in creds.token
    # Verify the refreshed token was persisted to disk, not just returned in memory
    assert "refreshed" in json.loads(path.read_text())["token"]


def test_requests_from_shared_service_get_own_authorized_transport() -> None:
    from google.oauth2.credentials import Credentials

    creds = Credentials(
        token="t",
        refresh_token="r",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="cid",
        client_secret="csec",
    )
    services = build_services(creds)

    req_a = services.drive.files().list(q="a")
    req_b = services.drive.files().list(q="b")

    assert req_a.http is not req_b.http
    assert req_a.http is not services.drive._http
    assert req_a.http.credentials is creds
    assert req_b.http.credentials is creds


def test_build_services_returns_three_services(mocker: pytest_mock.MockerFixture) -> None:
    fake_gmail, fake_cal, fake_drive = MagicMock(), MagicMock(), MagicMock()

    def _build(api: str, version: str, **kwargs):  # noqa: ARG001
        return {"gmail": fake_gmail, "calendar": fake_cal, "drive": fake_drive}[api]

    mocker.patch.object(auth_module, "build", side_effect=_build)
    creds = _FakeCreds()
    services = build_services(creds)  # type: ignore[arg-type]
    assert services.gmail is fake_gmail
    assert services.calendar is fake_cal
    assert services.drive is fake_drive


def test_scopes_are_exactly_the_four_required() -> None:
    assert SCOPES == (
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/drive",
    )


def test_stored_scopes_reads_token_file(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text(json.dumps({"token": "t", "scopes": ["a", "b"]}))
    assert stored_scopes(path) == ["a", "b"]


def test_stored_scopes_without_key_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text(json.dumps({"token": "t"}))
    assert stored_scopes(path) == []


def test_stored_scopes_unreadable_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text("not json")
    with pytest.raises(AuthError, match="unreadable"):
        stored_scopes(path)


def test_load_credentials_rejects_token_missing_required_scope(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    creds = _FakeCreds()
    creds._json["scopes"] = [s for s in SCOPES if not s.endswith("/drive")]
    save_credentials(creds, path)  # type: ignore[arg-type]
    with pytest.raises(AuthError, match="lacks scopes: https://www.googleapis.com/auth/drive;"):
        load_credentials(path)


def test_load_credentials_rejects_token_without_scopes_key(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text(json.dumps({"token": "t", "refresh_token": "r"}))
    with pytest.raises(AuthError, match="lacks scopes"):
        load_credentials(path)


def test_load_credentials_accepts_superset_of_scopes(
    tmp_path: Path, mocker: pytest_mock.MockerFixture
) -> None:
    path = tmp_path / "token.json"
    creds = _FakeCreds()
    creds._json["scopes"] = [*SCOPES, "https://www.googleapis.com/auth/drive.file"]
    save_credentials(creds, path)  # type: ignore[arg-type]
    mocker.patch.object(
        auth_module.Credentials, "from_authorized_user_file", return_value=_FakeCreds()
    )
    assert load_credentials(path).valid is True
