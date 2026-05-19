"""OAuth flow, credential persistence, and service builders.

Gmail/Calendar/Drive scopes are hardcoded here (single source of truth).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from hermes_google.core.errors import ServiceError

SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    # Drive: readonly covers files shared to us; drive.file covers own writes.
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
)


class AuthError(ServiceError):
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
        raise AuthError("credentials not found; run `hermes-google auth login`")
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


def run_install_flow(
    client_secret_path: Path, credentials_path: Path, *, headless: bool = False
) -> Credentials:
    if not client_secret_path.exists():
        raise AuthError("client secret file not found; check setup instructions")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), scopes=list(SCOPES))
    if headless:
        flow.redirect_uri = "http://localhost:8085"
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
        print(f"\nOpen this URL in any browser:\n\n{auth_url}\n")
        print("After authorizing, you'll be redirected to a page that won't load.")
        print("Copy the FULL URL from your browser's address bar and paste it here:\n")
        redirect_url = input("URL: ").strip()
        code = parse_qs(urlparse(redirect_url).query)["code"][0]
        flow.fetch_token(code=code)
        creds = flow.credentials
    else:
        creds = flow.run_local_server(port=0)
    save_credentials(creds, credentials_path)
    return creds


def revoke_credentials(path: Path) -> None:
    if path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(path), scopes=list(SCOPES))
            token = creds.token or creds.refresh_token
            if token:
                import requests

                requests.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": token},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10,
                )
        except Exception:  # noqa: BLE001
            pass  # best-effort; always delete local file regardless
        path.unlink()


def build_services(creds: Credentials) -> Services:
    return Services(
        gmail=build("gmail", "v1", credentials=creds),
        calendar=build("calendar", "v3", credentials=creds),
        drive=build("drive", "v3", credentials=creds),
    )
