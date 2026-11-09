"""Gmail drafts for the Hermes mailbox: build RFC 822 drafts and store them.

Every function that talks to Gmail takes a `service` argument. Nothing in this
module can send mail: the only Gmail calls are users().drafts() create, get,
update and delete.
"""

from __future__ import annotations

import base64
import mimetypes
import re
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage, Message
from email.policy import default as default_policy
from pathlib import Path

from hermes_google.core.mail import MailError

_ADDR_SPEC_RE = re.compile(r"[^\s@]+@[^\s@]+")


@dataclass(frozen=True)
class Recipient:
    name: str
    addr: str

    def render(self) -> str:
        return str(Address(display_name=self.name, addr_spec=self.addr))


def _parse_header_addresses(value: str) -> tuple[list[Recipient], list[str]]:
    """Parse an address header value into (usable recipients, rejected entries)."""
    header = default_policy.header_factory("To", value)
    good: list[Recipient] = []
    bad: list[str] = []
    for address in header.addresses:
        spec = address.addr_spec
        if spec.isascii() and _ADDR_SPEC_RE.fullmatch(spec):
            good.append(Recipient(name=address.display_name, addr=spec))
        else:
            bad.append(str(address))
    return good, bad


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
        msg.add_attachment(
            path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
        )
    for part in attachment_parts or []:
        maintype, subtype = part.get_content_type().split("/", 1)
        msg.add_attachment(
            part.get_payload(decode=True) or b"",
            maintype=maintype,
            subtype=subtype,
            filename=part.get_filename() or "attachment",
        )
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()
