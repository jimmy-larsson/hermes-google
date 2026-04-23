"""Tests for forward.py — forwarded-email unwrapping."""
from __future__ import annotations

from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default as default_policy
from pathlib import Path

import pytest

from hermes_google.core.forward import OriginalMessage, unwrap


def _load(fixtures_dir: Path, name: str) -> EmailMessage:
    raw = (fixtures_dir / name).read_bytes()
    return message_from_bytes(raw, policy=default_policy)  # type: ignore[return-value]


def test_unwrap_gmail_web_plain(fixtures_dir: Path) -> None:
    msg = _load(fixtures_dir, "fwd_plain_gmail_web.eml")
    original = unwrap(msg)
    assert isinstance(original, OriginalMessage)
    assert original.sender == "Acme Billing <billing@acme.example>"
    assert original.subject == "Q1 invoice from Acme"
    assert "Please find attached your Q1 invoice" in original.body
    assert "Forwarded message" not in original.body


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
    # Wrapping note from the forwarder is NOT part of the original body
    assert "Can you help me with this" not in original.body


def test_unwrap_non_forwarded_returns_message_as_is() -> None:
    msg = EmailMessage()
    msg["From"] = "direct@example.com"
    msg["Subject"] = "Not a forward"
    msg["Message-ID"] = "<direct-1@example.com>"
    msg.set_content("Just a regular message.")

    original = unwrap(msg)
    assert original.sender == "direct@example.com"
    assert original.subject == "Not a forward"
    assert "Just a regular message" in original.body


def test_original_message_fields_are_immutable() -> None:
    msg = OriginalMessage(sender="a", subject="b", body="c", in_reply_to=None)
    with pytest.raises((AttributeError, Exception)):
        msg.sender = "x"  # type: ignore[misc]
