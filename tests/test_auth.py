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
    with pytest.raises(AuthError, match="no credentials"):
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


def test_build_services_returns_three_services(mocker: pytest_mock.MockerFixture) -> None:
    fake_gmail, fake_cal, fake_drive = MagicMock(), MagicMock(), MagicMock()

    def _build(api: str, version: str, credentials):  # noqa: ARG001
        return {"gmail": fake_gmail, "calendar": fake_cal, "drive": fake_drive}[api]

    mocker.patch.object(auth_module, "build", side_effect=_build)
    creds = _FakeCreds()
    services = build_services(creds)  # type: ignore[arg-type]
    assert services.gmail is fake_gmail
    assert services.calendar is fake_cal
    assert services.drive is fake_drive
