"""Gmail drafts for the Hermes mailbox: build RFC 822 drafts and store them.

Every function that talks to Gmail takes a `service` argument. Nothing in this
module can send mail: the only Gmail calls are users().drafts() create, get,
update and delete.
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
import re
from dataclasses import dataclass
from email import errors as email_errors
from email import message_from_bytes
from email.headerregistry import Address, AddressHeader
from email.message import EmailMessage, Message
from email.policy import default as default_policy
from pathlib import Path
from typing import Any

from hermes_google.core.errors import api_failure
from hermes_google.core.forward import normalize_ids
from hermes_google.core.mail import MailError, MessageDetail

_ADDR_SPEC_RE = re.compile(r"[^\s@]+@[^\s@]+")
_LINE_ENDING_RE = re.compile(r"\r\n|\r|\n")


@dataclass(frozen=True)
class Recipient:
    name: str
    addr: str

    def render(self) -> str:
        return str(Address(display_name=self.name, addr_spec=self.addr))


# Relies on the parse-tree API behind AddressHeader (addresses, all_mailboxes, defects):
# a defect on the list means a broken list, a defect on one token means one bad address.
def _parse_header_addresses(value: str) -> tuple[list[Recipient], list[str]]:
    """Parse an address header value into (usable recipients, rejected entries)."""
    try:
        address_list = AddressHeader.value_parser(value)
    except Exception:  # noqa: BLE001
        return [], [value]
    if _has_invalid_defect(address_list.defects):
        return [], [value]
    good: list[Recipient] = []
    bad: list[str] = []
    for token in address_list.addresses:
        if _has_invalid_defect(token.all_defects):
            bad.append(str(token).strip())
            continue
        for mailbox in token.all_mailboxes:
            spec = mailbox.addr_spec or ""
            name = mailbox.display_name or ""
            shown = f"{name} <{spec}>".strip()
            if not (spec.isascii() and _ADDR_SPEC_RE.fullmatch(spec)):
                bad.append(shown)
                continue
            try:
                str(Address(display_name=name, addr_spec=spec))
            except Exception:  # noqa: BLE001
                bad.append(shown)
                continue
            good.append(Recipient(name=name, addr=spec))
    return good, bad


def _has_invalid_defect(defects) -> bool:
    return any(isinstance(defect, email_errors.InvalidHeaderDefect) for defect in defects)


def parse_recipients(entries: list[str]) -> list[Recipient]:
    """Strictly parse user-supplied recipients ('addr' or 'Name <addr>')."""
    out: list[Recipient] = []
    for entry in entries:
        if not entry.strip():
            continue
        good, bad = _parse_header_addresses(entry)
        if bad or not good:
            raise MailError(f"invalid recipient: {entry!r}")
        out.extend(good)
    return out


def build_draft_raw(
    *,
    to: list[Recipient],
    subject: str,
    body: str,
    cc: list[Recipient] | None = None,
    bcc: list[Recipient] | None = None,
    attachments: list[Path] | None = None,
    attachment_parts: list[Message] | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    if not to:
        raise MailError("a draft needs at least one To recipient")
    if "\n" in subject or "\r" in subject:
        raise MailError("the subject must be a single line")
    msg = EmailMessage()
    msg["To"] = ", ".join(r.render() for r in to)
    if cc:
        msg["Cc"] = ", ".join(r.render() for r in cc)
    if bcc:
        msg["Bcc"] = ", ".join(r.render() for r in bcc)
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references or in_reply_to:
        msg["References"] = references or in_reply_to
    msg.set_content(body)
    for path in attachments or []:
        if not path.is_file():
            raise MailError(f"attachment not found: {path}")
        mime_type, _ = mimetypes.guess_type(str(path))
        maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise MailError(f"attachment unreadable: {path}") from exc
        if maintype == "message":
            msg.add_attachment(message_from_bytes(data, policy=default_policy), filename=path.name)
        else:
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=path.name)
    for part in attachment_parts or []:
        filename = part.get_filename() or "attachment"
        if part.get_content_maintype() == "message":
            msg.add_attachment(part.get_payload(0), filename=filename)
            continue
        maintype, subtype = part.get_content_type().split("/", 1)
        msg.add_attachment(
            part.get_payload(decode=True) or b"",
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


@dataclass(frozen=True)
class DraftRef:
    draft_id: str
    message_id: str
    thread_id: str | None
    to: list[str]
    cc: list[str]
    subject: str
    warning: str | None = None


@dataclass(frozen=True)
class ReplyContext:
    to: list[Recipient]
    cc: list[Recipient]
    subject: str
    in_reply_to: str | None
    references: str | None
    thread_id: str | None
    warning: str | None


def _draft_ref(
    resp: dict[str, Any], *, to: list[Recipient], cc: list[Recipient], subject: str
) -> DraftRef:
    try:
        message = resp["message"]
        return DraftRef(
            draft_id=resp["id"],
            message_id=message["id"],
            thread_id=message.get("threadId"),
            to=[r.render() for r in to],
            cc=[r.render() for r in cc],
            subject=subject,
        )
    except (KeyError, TypeError) as exc:
        raise MailError("unexpected draft response format") from exc


def _message_body(raw: str, thread_id: str | None) -> dict[str, Any]:
    message: dict[str, Any] = {"raw": raw}
    if thread_id:
        message["threadId"] = thread_id
    return {"message": message}


def create_draft(
    service: Any,
    *,
    to: list[Recipient],
    subject: str,
    body: str,
    cc: list[Recipient] | None = None,
    attachments: list[Path] | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    thread_id: str | None = None,
) -> DraftRef:
    raw = build_draft_raw(
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        attachments=attachments,
        in_reply_to=in_reply_to,
        references=references,
    )
    try:
        resp = (
            service.users()
            .drafts()
            .create(userId="me", body=_message_body(raw, thread_id))
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise MailError(api_failure("create draft", exc)) from exc
    return _draft_ref(resp, to=to, cc=cc or [], subject=subject)


def delete_draft(service: Any, *, draft_id: str) -> None:
    try:
        service.users().drafts().delete(userId="me", id=draft_id).execute()
    except Exception as exc:  # noqa: BLE001
        raise MailError(api_failure(f"delete draft {draft_id}", exc)) from exc


def _reply_subject(subject: str) -> str:
    cleaned = subject.strip()
    if cleaned.lower().startswith("re:"):
        return cleaned
    return f"Re: {cleaned}".rstrip()


def _dedupe(recipients: list[Recipient], *, exclude: set[str]) -> list[Recipient]:
    seen: set[str] = set()
    out: list[Recipient] = []
    for recipient in recipients:
        key = recipient.addr.lower()
        if key in exclude or key in seen:
            continue
        seen.add(key)
        out.append(recipient)
    return out


def reply_context(detail: MessageDetail, *, user_email: str, hermes_email: str) -> ReplyContext:
    rejected: list[str] = []

    def parse(value: str | None) -> list[Recipient]:
        if not value:
            return []
        good, bad = _parse_header_addresses(str(value))
        rejected.extend(bad)
        return good

    origin = parse(detail.original_reply_to) or parse(detail.original_sender)
    own = {user_email.lower(), hermes_email.lower()}
    if origin:
        to = _dedupe(origin + parse(detail.original_to), exclude=own) or _dedupe(
            origin, exclude=set()
        )
    else:
        to = []
    cc = _dedupe(parse(detail.original_cc), exclude=own | {r.addr.lower() for r in to})

    if detail.rfc_message_id:
        parent: str | None = detail.rfc_message_id
        chain = detail.references or detail.in_reply_to
        references: str | None = f"{chain} {parent}" if chain else parent
        thread_id: str | None = detail.thread_id or None
    else:
        parent = detail.in_reply_to
        references = detail.references or parent
        thread_id = None

    warning = f"ignored unusable addresses: {', '.join(rejected)}" if rejected else None
    return ReplyContext(
        to=to,
        cc=cc,
        subject=_reply_subject(detail.original_subject),
        in_reply_to=parent,
        references=references,
        thread_id=thread_id,
        warning=warning,
    )


@dataclass(frozen=True)
class _StoredDraft:
    to: list[Recipient]
    cc: list[Recipient]
    bcc: list[Recipient]
    subject: str
    body: str | None
    attachment_parts: list[Message]
    in_reply_to: str | None
    references: str | None
    thread_id: str | None


def _load_stored_draft(service: Any, draft_id: str) -> _StoredDraft:
    try:
        resp = service.users().drafts().get(userId="me", id=draft_id, format="raw").execute()
    except Exception as exc:  # noqa: BLE001
        raise MailError(api_failure(f"fetch draft {draft_id}", exc)) from exc
    try:
        message = resp["message"]
        raw_bytes = base64.urlsafe_b64decode(message["raw"])
        thread_id = message.get("threadId")
    except (KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise MailError("unexpected draft response format") from exc
    parsed = message_from_bytes(raw_bytes, policy=default_policy)
    to, _ = _parse_header_addresses(str(parsed.get("To", "")))
    cc, _ = _parse_header_addresses(str(parsed.get("Cc", "")))
    bcc, _ = _parse_header_addresses(str(parsed.get("Bcc", "")))
    body_part = parsed.get_body(preferencelist=("plain",))
    body = (
        "\n".join(_LINE_ENDING_RE.split(body_part.get_content())) if body_part is not None else None
    )
    return _StoredDraft(
        to=to,
        cc=cc,
        bcc=bcc,
        subject=str(parsed.get("Subject", "")),
        body=body,
        attachment_parts=list(parsed.iter_attachments()),
        in_reply_to=normalize_ids(parsed.get("In-Reply-To")),
        references=normalize_ids(parsed.get("References")),
        thread_id=thread_id,
    )


def update_draft(
    service: Any,
    *,
    draft_id: str,
    to: list[Recipient] | None = None,
    cc: list[Recipient] | None = None,
    subject: str | None = None,
    body: str | None = None,
    attachments: list[Path] | None = None,
) -> DraftRef:
    if to is None and cc is None and subject is None and body is None and attachments is None:
        raise MailError("nothing to update")
    stored = _load_stored_draft(service, draft_id)
    new_to = stored.to if to is None else to
    new_cc = stored.cc if cc is None else cc
    new_subject = stored.subject if subject is None else subject
    new_body = stored.body if body is None else body
    if new_body is None:
        raise MailError("stored draft has no plain-text body; pass body explicitly")
    if attachments is None:
        parts: list[Message] = stored.attachment_parts
        files: list[Path] | None = None
    else:
        parts = []
        files = attachments
    raw = build_draft_raw(
        to=new_to,
        subject=new_subject,
        body=new_body,
        cc=new_cc or None,
        bcc=stored.bcc or None,
        attachments=files,
        attachment_parts=parts,
        in_reply_to=stored.in_reply_to,
        references=stored.references,
    )
    try:
        resp = (
            service.users()
            .drafts()
            .update(userId="me", id=draft_id, body=_message_body(raw, stored.thread_id))
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise MailError(api_failure(f"update draft {draft_id}", exc)) from exc
    return _draft_ref(resp, to=new_to, cc=new_cc, subject=new_subject)
