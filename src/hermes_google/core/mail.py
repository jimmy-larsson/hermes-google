"""Gmail operations. Every function takes a `service` argument.

No config imports here — callers pass paths explicitly so this module stays
easy to unit-test with MagicMock services.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default as default_policy
from pathlib import Path
from typing import Any

from hermes_google.core.forward import unwrap


class MailError(Exception):
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
        raise MailError(str(exc)) from exc

    ids = [m["id"] for m in resp.get("messages", [])]
    out: list[PendingMessage] = []
    for mid in ids:
        meta = (
            service.users().messages().get(userId="me", id=mid, format="metadata").execute()
        )
        out.append(_to_pending(meta))
    return out


def list_pending(service: Any, *, limit: int = 20) -> list[PendingMessage]:
    return _list_and_hydrate(service, query="is:unread in:inbox", limit=limit)


def search(service: Any, *, query: str, limit: int = 20) -> list[PendingMessage]:
    return _list_and_hydrate(service, query=query, limit=limit)


def _walk_attachments(
    service: Any, message_id: str, parsed: EmailMessage, cache_dir: Path
) -> list[Path]:
    paths: list[Path] = []
    if not parsed.is_multipart():
        return paths
    target_dir = cache_dir / message_id
    target_dir.mkdir(parents=True, exist_ok=True)
    for part in parsed.walk():
        filename = part.get_filename()
        if not filename:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        out = target_dir / filename
        out.write_bytes(payload)
        paths.append(out)
    return paths


def get_message(service: Any, *, message_id: str, cache_dir: Path) -> MessageDetail:
    try:
        resp = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="raw")
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise MailError(f"failed to fetch message {message_id}: {exc}") from exc

    raw_bytes = base64.urlsafe_b64decode(resp["raw"])
    parsed: EmailMessage = message_from_bytes(raw_bytes, policy=default_policy)  # type: ignore[assignment]
    original = unwrap(parsed)
    attachments = _walk_attachments(service, message_id, parsed, cache_dir)
    return MessageDetail(
        id=resp["id"],
        thread_id=resp.get("threadId", ""),
        original_sender=original.sender,
        original_subject=original.subject,
        original_body=original.body,
        in_reply_to=original.in_reply_to,
        attachment_paths=attachments,
    )
