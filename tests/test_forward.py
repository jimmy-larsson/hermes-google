"""Tests for forward.py — forwarded-email unwrapping."""

from __future__ import annotations

import dataclasses
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default as default_policy
from pathlib import Path

import pytest

from hermes_google.core.forward import OriginalMessage, strip_html, unwrap


def _load(fixtures_dir: Path, name: str) -> EmailMessage:
    raw = (fixtures_dir / name).read_bytes()
    return message_from_bytes(raw, policy=default_policy)  # type: ignore[return-value]


def test_unwrap_gmail_web_plain(fixtures_dir: Path) -> None:
    msg = _load(fixtures_dir, "fwd_plain_gmail_web.eml")
    msg["In-Reply-To"] = "<thread@example.com>"
    original = unwrap(msg)
    assert isinstance(original, OriginalMessage)
    assert original.sender == "Acme Billing <billing@acme.example>"
    assert original.subject == "Q1 invoice from Acme"
    assert "Please find attached your Q1 invoice" in original.body
    assert "Forwarded message" not in original.body
    assert original.in_reply_to == "<thread@example.com>"
    assert original.forwarding_note is None or isinstance(original.forwarding_note, str)


def test_unwrap_gmail_mobile_plain(fixtures_dir: Path) -> None:
    msg = _load(fixtures_dir, "fwd_plain_gmail_mobile.eml")
    original = unwrap(msg)
    assert original.sender == "Alex Chen <alex@board.example>"
    assert original.subject == "Board meeting prep"
    assert "Begin forwarded message" not in original.body
    assert "attaching the agenda" in original.body


def test_unwrap_manual_client(fixtures_dir: Path) -> None:
    msg = _load(fixtures_dir, "fwd_manual_client.eml")
    original = unwrap(msg)
    assert original.sender == "Legal <legal@counsel.example>"
    assert original.subject == "Contract revision v3"
    assert "Revised draft attached" in original.body
    assert "Can you help me with this" not in original.body
    assert original.forwarding_note is not None
    assert "Can you help me with this" in original.forwarding_note


def test_unwrap_non_forwarded_returns_message_as_is() -> None:
    msg = EmailMessage()
    msg["From"] = "direct@example.com"
    msg["Subject"] = "Not a forward"
    msg["Message-ID"] = "<direct-1@example.com>"
    msg["In-Reply-To"] = "<prev@example.com>"
    msg.set_content("Just a regular message.")

    original = unwrap(msg)
    assert original.sender == "direct@example.com"
    assert original.subject == "Not a forward"
    assert "Just a regular message" in original.body
    assert original.in_reply_to == "<prev@example.com>"
    assert original.forwarding_note is None


def test_strip_html_removes_tags() -> None:
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_strip_html_decodes_entities() -> None:
    assert strip_html("&lt;script&gt;alert(1)&lt;/script&gt;") == "<script>alert(1)</script>"


def test_strip_html_plain_text_passthrough() -> None:
    assert strip_html("no html here") == "no html here"


def test_unwrap_html_only_email_strips_tags() -> None:
    msg = EmailMessage()
    msg["From"] = "html@example.com"
    msg["Subject"] = "HTML only"
    msg.set_content("<p>Hello <b>world</b></p>", subtype="html")

    original = unwrap(msg)
    assert "Hello world" in original.body
    assert "<p>" not in original.body
    assert "<b>" not in original.body


def test_unwrap_multipart_prefers_plain_over_html() -> None:
    msg = EmailMessage()
    msg["From"] = "multi@example.com"
    msg["Subject"] = "Both parts"
    msg.set_content("Plain text version.")
    msg.add_alternative("<p>HTML version.</p>", subtype="html")

    original = unwrap(msg)
    assert original.body == "Plain text version."
    assert "<p>" not in original.body


def test_unwrap_multipart_html_fallback() -> None:
    """Multipart with only HTML part falls back to stripped HTML."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.policy import default as dp

    mp = MIMEMultipart()
    mp["From"] = "fallback@example.com"
    mp["Subject"] = "HTML fallback"
    html_part = MIMEText("<p>Only <em>HTML</em> here</p>", "html")
    mp.attach(html_part)

    parsed: EmailMessage = message_from_bytes(mp.as_bytes(), policy=dp)  # type: ignore[assignment]
    original = unwrap(parsed)
    assert "Only HTML here" in original.body
    assert "<p>" not in original.body


def test_unwrap_forwarding_note_preserved() -> None:
    msg = EmailMessage()
    msg["From"] = "user@example.com"
    msg["Subject"] = "Fwd: Important"
    msg.set_content(
        "Please review this urgently\n\n"
        "---------- Forwarded message ---------\n"
        "From: sender@example.com\n"
        "Subject: Important\n\n"
        "The actual content."
    )
    original = unwrap(msg)
    assert original.forwarding_note == "Please review this urgently"
    assert original.body == "The actual content."
    assert original.sender == "sender@example.com"


def test_unwrap_empty_forwarding_note_is_none() -> None:
    msg = EmailMessage()
    msg["From"] = "user@example.com"
    msg["Subject"] = "Fwd: Stuff"
    msg.set_content(
        "---------- Forwarded message ---------\n"
        "From: sender@example.com\n"
        "Subject: Stuff\n\n"
        "Body here."
    )
    original = unwrap(msg)
    assert original.forwarding_note is None


def test_original_message_fields_are_immutable() -> None:
    msg = OriginalMessage(sender="a", subject="b", body="c", in_reply_to=None, forwarding_note=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        msg.sender = "x"  # type: ignore[misc]


def test_unwrap_direct_message_exposes_headers_and_normalises_folded_ids() -> None:
    raw = (
        b"From: Alice <alice@example.com>\r\n"
        b"To: Jimmy <jimmy@example.com>, hermes@example.com\r\n"
        b"Cc: Bob <bob@example.com>\r\n"
        b"Reply-To: Alice Work <alice@work.example>\r\n"
        b"Subject: Direct\r\n"
        b"Message-ID: <direct-1@example.com>\r\n"
        b"In-Reply-To: <a@example.com>\r\n\t<b@example.com>\r\n"
        b"References: <root@example.com>\r\n\t<a@example.com>\r\n"
        b'Content-Type: text/plain; charset="UTF-8"\r\n'
        b"\r\n"
        b"Body.\r\n"
    )
    msg = message_from_bytes(raw, policy=default_policy)
    original = unwrap(msg)  # type: ignore[arg-type]
    assert original.message_id == "<direct-1@example.com>"
    assert original.in_reply_to == "<a@example.com> <b@example.com>"
    assert original.references == "<root@example.com> <a@example.com>"
    assert original.to == "Jimmy <jimmy@example.com>, hermes@example.com"
    assert original.cc == "Bob <bob@example.com>"
    assert original.reply_to == "Alice Work <alice@work.example>"


def test_unwrap_direct_message_without_headers_yields_none() -> None:
    msg = EmailMessage()
    msg["From"] = "direct@example.com"
    msg["Subject"] = "Plain"
    msg.set_content("Body.")
    original = unwrap(msg)
    assert original.message_id is None
    assert original.references is None
    assert original.to is None
    assert original.cc is None
    assert original.reply_to is None


def test_unwrap_manual_forward_threads_from_wrapper_headers(fixtures_dir: Path) -> None:
    msg = _load(fixtures_dir, "fwd_plain_gmail_web.eml")
    msg["In-Reply-To"] = "<orig-001@acme.example>"
    msg["References"] = "<root@acme.example> <orig-001@acme.example>"
    original = unwrap(msg)
    assert original.message_id is None
    assert original.in_reply_to == "<orig-001@acme.example>"
    assert original.references == "<root@acme.example> <orig-001@acme.example>"
    assert original.to == "Jimmy Larsson <jimmy@example.com>"
    assert original.cc is None
    assert original.reply_to is None


def test_unwrap_manual_forward_reads_inner_cc_and_reply_to() -> None:
    msg = EmailMessage()
    msg["From"] = "Jimmy <jimmy@example.com>"
    msg["Subject"] = "Fwd: Agenda"
    msg.set_content(
        "---------- Forwarded message ---------\n"
        "From: Alex Chen <alex@board.example>\n"
        "Date: Wed, 22 Apr 2026 at 18:47\n"
        "Subject: Agenda\n"
        "To: Jimmy <jimmy@example.com>, Alexandra <alex@example.com>\n"
        "Cc: Board <board@board.example>\n"
        "Reply-To: Alex Work <alex.work@board.example>\n\n"
        "Body."
    )
    original = unwrap(msg)
    assert original.sender == "Alex Chen <alex@board.example>"
    assert original.to == "Jimmy <jimmy@example.com>, Alexandra <alex@example.com>"
    assert original.cc == "Board <board@board.example>"
    assert original.reply_to == "Alex Work <alex.work@board.example>"
    assert original.body == "Body."
