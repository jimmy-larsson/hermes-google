"""Gmail operations. Every function takes a `service` argument.

No config imports here — callers pass paths explicitly so this module stays
easy to unit-test with MagicMock services.
"""

from __future__ import annotations

import base64
import binascii
import os.path
from dataclasses import dataclass
from email import message_from_bytes
from email.message import EmailMessage
from email.mime.text import MIMEText
from email.policy import default as default_policy
from pathlib import Path
from typing import Any

from hermes_google.core.errors import ServiceError
from hermes_google.core.forward import unwrap


class MailError(ServiceError):
    """Raised on Gmail API failures."""


@dataclass(frozen=True)
class PendingMessage:
    id: str
    thread_id: str
    sender: str
    subject: str
    date: str
    snippet: str


@dataclass(frozen=True)
class MessageDetail:
    id: str
    thread_id: str
    original_sender: str
    original_subject: str
    original_body: str
    in_reply_to: str | None
    attachment_paths: list[Path]


def _header(payload: dict[str, Any], name: str) -> str:
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _to_pending(meta: dict[str, Any]) -> PendingMessage:
    payload = meta.get("payload", {})
    return PendingMessage(
        id=meta["id"],
        thread_id=meta.get("threadId", ""),
        sender=_header(payload, "From"),
        subject=_header(payload, "Subject"),
        date=_header(payload, "Date"),
        snippet=meta.get("snippet", ""),
    )


def _unique_path(base: Path, filename: str) -> Path:
    candidate = base / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for i in range(1, 1000):
        alt = base / f"{stem}-{i}{suffix}"
        if not alt.exists():
            return alt
    raise MailError(f"too many filename collisions for {filename}")


def _list_and_hydrate(
    service: Any, *, query: str | None, limit: int, label_ids: list[str] | None = None
) -> list[PendingMessage]:
    try:
        kwargs: dict[str, Any] = {"userId": "me", "maxResults": limit}
        if query is not None:
            kwargs["q"] = query
        if label_ids is not None:
            kwargs["labelIds"] = label_ids
        resp = service.users().messages().list(**kwargs).execute()
    except Exception as exc:  # noqa: BLE001 - Google client raises HttpError; keep broad for tests
        raise MailError("failed to list messages") from exc

    ids = [m["id"] for m in resp.get("messages", [])]
    out: list[PendingMessage] = []
    for mid in ids:
        try:
            meta = service.users().messages().get(userId="me", id=mid, format="metadata").execute()
        except Exception:  # noqa: BLE001
            continue  # skip messages that disappeared between list and hydrate
        out.append(_to_pending(meta))
    return out


def list_pending(service: Any, *, limit: int = 20) -> list[PendingMessage]:
    return _list_and_hydrate(service, query="is:unread in:inbox", limit=limit)


def search(service: Any, *, query: str, limit: int = 20) -> list[PendingMessage]:
    return _list_and_hydrate(service, query=query, limit=limit)


def _walk_attachments(message_id: str, parsed: EmailMessage, cache_dir: Path) -> list[Path]:
    paths: list[Path] = []
    if not parsed.is_multipart():
        return paths
    target_dir = cache_dir / message_id
    for part in parsed.walk():
        filename = part.get_filename()
        if not filename:
            continue
        safe_name = os.path.basename(filename)
        if not safe_name or safe_name in {".", ".."} or "/" in safe_name or "\\" in safe_name:
            continue  # skip suspicious/unsafe filenames
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        target_dir.mkdir(parents=True, exist_ok=True)  # lazy — only on first real attachment
        out = _unique_path(target_dir, safe_name)
        if not str(out.resolve()).startswith(str(target_dir.resolve()) + os.sep):
            continue
        out.write_bytes(payload)
        paths.append(out)
    return paths


def get_message(service: Any, *, message_id: str, cache_dir: Path) -> MessageDetail:
    try:
        resp = service.users().messages().get(userId="me", id=message_id, format="raw").execute()
    except Exception as exc:  # noqa: BLE001
        raise MailError(f"failed to fetch message {message_id}") from exc

    try:
        raw_field = resp["raw"]
        raw_bytes = base64.urlsafe_b64decode(raw_field)
        parsed: EmailMessage = message_from_bytes(raw_bytes, policy=default_policy)  # type: ignore[assignment]
    except (KeyError, binascii.Error, ValueError) as exc:
        raise MailError(f"malformed response for message {message_id}") from exc

    original = unwrap(parsed)
    attachments = _walk_attachments(message_id, parsed, cache_dir)
    return MessageDetail(
        id=resp["id"],
        thread_id=resp.get("threadId", ""),
        original_sender=original.sender,
        original_subject=original.subject,
        original_body=original.body,
        in_reply_to=original.in_reply_to,
        attachment_paths=attachments,
    )


def _build_raw(to: str, subject: str, body: str, in_reply_to: str | None = None) -> str:
    # From is populated server-side by Gmail when userId="me".
    msg = MIMEText(body, _charset="utf-8")
    msg["To"] = to
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def send_draft(
    service: Any,
    *,
    user_email: str,
    to: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
) -> str:
    if to.strip().lower() != user_email.strip().lower():
        raise MailError("send_draft: destination must match the configured user email")
    try:
        raw = _build_raw(to, subject, body, in_reply_to=in_reply_to)
        resp = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except Exception as exc:  # noqa: BLE001
        raise MailError("failed to send draft") from exc
    try:
        return resp["id"]
    except KeyError as exc:
        raise MailError("unexpected send response format") from exc


def mark_read(service: Any, *, message_id: str) -> None:
    try:
        service.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()
    except Exception as exc:  # noqa: BLE001
        raise MailError("failed to mark read") from exc


def archive(service: Any, *, message_id: str) -> None:
    try:
        service.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["INBOX"]}
        ).execute()
    except Exception as exc:  # noqa: BLE001
        raise MailError("failed to archive") from exc
