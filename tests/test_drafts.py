"""Tests for drafts.py: recipients, draft building, reply context, Gmail Drafts calls."""

from __future__ import annotations

import base64
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default as default_policy
from pathlib import Path

import pytest

from hermes_google.core.drafts import (
    Recipient,
    build_draft_raw,
    parse_recipients,
)
from hermes_google.core.mail import MailError


def _decode(raw_b64: str) -> EmailMessage:
    return message_from_bytes(  # type: ignore[return-value]
        base64.urlsafe_b64decode(raw_b64), policy=default_policy
    )


def test_parse_recipients_accepts_plain_and_named_addresses() -> None:
    got = parse_recipients(["a@x.com", "Jimmy Larsson <j@x.com>"])
    assert got == [
        Recipient(name="", addr="a@x.com"),
        Recipient(name="Jimmy Larsson", addr="j@x.com"),
    ]


def test_parse_recipients_keeps_quoted_comma_name_as_one_recipient() -> None:
    assert parse_recipients(['"Larsson, Jimmy" <j@x.com>']) == [
        Recipient(name="Larsson, Jimmy", addr="j@x.com")
    ]


def test_parse_recipients_accepts_non_ascii_display_name() -> None:
    assert parse_recipients(["Jörg Müller <j@x.com>"]) == [
        Recipient(name="Jörg Müller", addr="j@x.com")
    ]


def test_parse_recipients_skips_blank_entries() -> None:
    assert parse_recipients(["", "  ", "a@x.com"]) == [Recipient(name="", addr="a@x.com")]


@pytest.mark.parametrize("bad", ["Larsson", "Jörg <jörg@x.com>", "Larsson, Jimmy <j@x.com>", "<>"])
def test_parse_recipients_rejects_unusable_entries(bad: str) -> None:
    with pytest.raises(MailError, match="invalid recipient"):
        parse_recipients([bad])


def test_recipient_render_quotes_comma_names_and_round_trips() -> None:
    rendered = Recipient(name="Larsson, Jimmy", addr="j@x.com").render()
    assert rendered == '"Larsson, Jimmy" <j@x.com>'
    assert parse_recipients([rendered]) == [Recipient(name="Larsson, Jimmy", addr="j@x.com")]
    assert Recipient(name="", addr="j@x.com").render() == "j@x.com"
    assert Recipient(name="Jörg Müller", addr="j@x.com").render() == "Jörg Müller <j@x.com>"


def test_build_draft_raw_sets_headers_and_body() -> None:
    raw = build_draft_raw(
        to=[Recipient("Alice", "alice@example.com")],
        cc=[Recipient("", "bob@example.com")],
        subject="Re: Hello",
        body="Hi Alice",
        in_reply_to="<orig@example.com>",
        references="<root@example.com> <orig@example.com>",
    )
    msg = _decode(raw)
    assert [(a.display_name, a.addr_spec) for a in msg["To"].addresses] == [
        ("Alice", "alice@example.com")
    ]
    assert [a.addr_spec for a in msg["Cc"].addresses] == ["bob@example.com"]
    assert msg["Subject"] == "Re: Hello"
    assert msg["In-Reply-To"] == "<orig@example.com>"
    assert msg["References"] == "<root@example.com> <orig@example.com>"
    assert "From" not in msg
    assert msg.get_body(preferencelist=("plain",)).get_content() == "Hi Alice\n"


def test_build_draft_raw_omits_optional_headers() -> None:
    msg = _decode(build_draft_raw(to=[Recipient("", "a@x.com")], subject="s", body="b"))
    assert "Cc" not in msg
    assert "In-Reply-To" not in msg
    assert "References" not in msg


def test_build_draft_raw_references_default_to_in_reply_to() -> None:
    msg = _decode(
        build_draft_raw(
            to=[Recipient("", "a@x.com")], subject="s", body="b", in_reply_to="<p@x.com>"
        )
    )
    assert msg["References"] == "<p@x.com>"


def test_build_draft_raw_renders_non_ascii_names_readably() -> None:
    msg = _decode(
        build_draft_raw(
            to=[Recipient("Jörg Müller", "j@x.com"), Recipient("Larsson, Jimmy", "k@x.com")],
            subject="s",
            body="b",
        )
    )
    assert [(a.display_name, a.addr_spec) for a in msg["To"].addresses] == [
        ("Jörg Müller", "j@x.com"),
        ("Larsson, Jimmy", "k@x.com"),
    ]


def test_build_draft_raw_requires_a_recipient() -> None:
    with pytest.raises(MailError, match="at least one To recipient"):
        build_draft_raw(to=[], subject="s", body="b")


def test_build_draft_raw_rejects_multiline_subject() -> None:
    with pytest.raises(MailError, match="single line"):
        build_draft_raw(to=[Recipient("", "a@x.com")], subject="a\nb", body="b")


def test_build_draft_raw_attaches_files(tmp_path: Path) -> None:
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    msg = _decode(
        build_draft_raw(to=[Recipient("", "a@x.com")], subject="s", body="b", attachments=[pdf])
    )
    parts = list(msg.iter_attachments())
    assert [(p.get_filename(), p.get_content_type()) for p in parts] == [
        ("report.pdf", "application/pdf")
    ]
    assert parts[0].get_payload(decode=True) == b"%PDF-1.4 fake"
    assert msg.get_body(preferencelist=("plain",)).get_content() == "b\n"


def test_build_draft_raw_missing_attachment_raises(tmp_path: Path) -> None:
    with pytest.raises(MailError, match="attachment not found"):
        build_draft_raw(
            to=[Recipient("", "a@x.com")],
            subject="s",
            body="b",
            attachments=[tmp_path / "nope.pdf"],
        )


def test_build_draft_raw_carries_existing_parts(tmp_path: Path) -> None:
    txt = tmp_path / "a.txt"
    txt.write_bytes(b"one")
    first = _decode(
        build_draft_raw(to=[Recipient("", "a@x.com")], subject="s", body="b", attachments=[txt])
    )
    parts = list(first.iter_attachments())

    second = _decode(
        build_draft_raw(
            to=[Recipient("", "a@x.com")], subject="s", body="new", attachment_parts=parts
        )
    )
    assert [(p.get_filename(), p.get_payload(decode=True)) for p in second.iter_attachments()] == [
        ("a.txt", b"one")
    ]
    assert second.get_body(preferencelist=("plain",)).get_content() == "new\n"
