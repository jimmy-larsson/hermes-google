"""OAuth flow, credential persistence, and service builders.

Gmail/Calendar/Drive scopes are hardcoded here (single source of truth).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    # Drive: readonly covers files shared to us; drive.file covers own writes.
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
)


class AuthError(Exception):
    """Raised on credential / OAuth failures."""


@dataclass(frozen=True)
class Services:
    gmail: object
    calendar: object
    drive: object


def save_credentials(creds: Credentials, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(creds.to_json())
    os.replace(tmp, path)


def load_credentials(path: Path) -> Credentials:
    if not path.exists():
        raise AuthError(f"no credentials at {path}; run `hermes-google auth login`")
    creds = Credentials.from_authorized_user_file(str(path), scopes=list(SCOPES))
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            save_credentials(creds, path)
        else:
            raise AuthError(
                "credentials expired and cannot refresh; run `hermes-google auth login`"
            )
    return creds


def run_install_flow(client_secret_path: Path, credentials_path: Path) -> Credentials:
    if not client_secret_path.exists():
        raise AuthError(f"client secret not found at {client_secret_path}")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secret_path), scopes=list(SCOPES)
    )
    creds = flow.run_local_server(port=0)
    save_credentials(creds, credentials_path)
    return creds


def revoke_credentials(path: Path) -> None:
    # TODO: also POST to https://oauth2.googleapis.com/revoke per spec §8.3
    #   — deferred to CLI (Task 13).
    if path.exists():
        path.unlink()


def build_services(creds: Credentials) -> Services:
    return Services(
        gmail=build("gmail", "v1", credentials=creds),
        calendar=build("calendar", "v3", credentials=creds),
        drive=build("drive", "v3", credentials=creds),
    )
