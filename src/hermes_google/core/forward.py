"""Parse a forwarded email into its original-message view.

Supports three formats:
1. Gmail web "---------- Forwarded message ---------" delimiter
2. Gmail iOS/macOS "Begin forwarded message:" delimiter
3. Legacy "-----Original Message-----" delimiter (Outlook-style)

Non-forwarded messages pass through unchanged.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from email.message import EmailMessage
from html.parser import HTMLParser
from io import StringIO


@dataclass(frozen=True)
class OriginalMessage:
    sender: str
    subject: str
    body: str
    in_reply_to: str | None


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._buf = StringIO()

    def handle_data(self, data: str) -> None:
        self._buf.write(data)

    def get_text(self) -> str:
        return html.unescape(self._buf.getvalue())


def strip_html(value: str) -> str:
    """Remove HTML tags and decode entities, returning plain text."""
    parser = _HTMLTextExtractor()
    parser.feed(value)
    return parser.get_text()


_DELIMITERS = [
    re.compile(r"-{5,}\s*Forwarded message\s*-{5,}", re.IGNORECASE),
    re.compile(r"Begin forwarded message:\s*", re.IGNORECASE),
    re.compile(r"-{5,}\s*Original Message\s*-{5,}", re.IGNORECASE),
]

_HEADER_LINE = re.compile(
    r"^\s*(From|Subject|Date|To|Sent|Cc|Bcc|Reply-To)\s*:\s*(.*)$", re.IGNORECASE
)
_KEEP_HEADERS = {"from", "subject", "date", "to"}


def _get_plain_body(msg: EmailMessage) -> str:
    if msg.is_multipart():
        plain = ""
        html_fallback = ""
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and not plain:
                plain = part.get_content()
            elif ct == "text/html" and not html_fallback:
                html_fallback = part.get_content()
        return plain or (strip_html(html_fallback) if html_fallback else "")
    ct = msg.get_content_type()
    if ct == "text/plain":
        return msg.get_content()
    if ct == "text/html":
        return strip_html(msg.get_content())
    return ""


def _split_on_delimiter(body: str) -> tuple[str, str] | None:
    for pattern in _DELIMITERS:
        m = pattern.search(body)
        if m:
            return body[: m.start()], body[m.end() :]
    return None


def _parse_inner_headers(chunk: str) -> tuple[dict[str, str], str]:
    """Walk consecutive 'Header: value' lines and return (headers, remaining_body)."""
    lines = chunk.lstrip().splitlines()
    headers: dict[str, str] = {}
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if not line.strip():
            idx += 1
            # headers end at first blank line, but tolerate leading blank
            if headers:
                break
            continue
        match = _HEADER_LINE.match(line)
        if not match:
            if headers:
                break
            idx += 1
            continue
        key = match.group(1).lower()
        if key in _KEEP_HEADERS:
            headers[key] = match.group(2).strip()
        idx += 1
    return headers, "\n".join(lines[idx:]).strip()


def unwrap(msg: EmailMessage) -> OriginalMessage:
    body = _get_plain_body(msg)
    split = _split_on_delimiter(body)

    if split is None:
        return OriginalMessage(
            sender=msg.get("From", ""),
            subject=msg.get("Subject", ""),
            body=body.strip(),
            in_reply_to=msg.get("In-Reply-To"),
        )

    # The forwarder's preamble (e.g. "Can you help with this?") is intentionally
    # dropped — callers only need the original message content.
    _wrap_note, after = split
    headers, inner_body = _parse_inner_headers(after)
    return OriginalMessage(
        sender=headers.get("from", msg.get("From", "")),
        subject=headers.get("subject", msg.get("Subject", "")),
        body=inner_body,
        in_reply_to=msg.get("In-Reply-To"),
    )
