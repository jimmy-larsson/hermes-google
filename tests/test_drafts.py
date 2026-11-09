"""Tests for drafts.py: recipients, draft building, reply context, Gmail Drafts calls."""

from __future__ import annotations

import base64
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default as default_policy
from pathlib import Path
from unittest.mock import MagicMock

import httplib2
import pytest
from googleapiclient.errors import HttpError

from hermes_google.core.drafts import (
    DraftRef,
    Recipient,
    build_draft_raw,
    create_draft,
    delete_draft,
    parse_recipients,
    reply_context,
    update_draft,
)
from hermes_google.core.mail import MailError, MessageDetail


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


USER = "jimmy@example.com"
HERMES = "hermes@example.com"


def _detail(**overrides) -> MessageDetail:
    base = dict(
        id="m1",
        thread_id="t1",
        sender="Alice <alice@example.com>",
        original_sender="Alice <alice@example.com>",
        original_subject="Hello",
        original_body="...",
        in_reply_to=None,
        forwarding_note=None,
        attachment_paths=[],
    )
    base.update(overrides)
    return MessageDetail(**base)


def _ctx(**overrides):
    return reply_context(_detail(**overrides), user_email=USER, hermes_email=HERMES)


def test_reply_context_reply_all_drops_own_addresses_and_duplicates() -> None:
    ctx = _ctx(
        original_to=(
            "Jimmy <jimmy@example.com>, Hermes <hermes@example.com>, Carol <carol@example.com>"
        ),
        original_cc="Dave <dave@example.com>, carol@example.com, JIMMY@example.com",
        rfc_message_id="<orig@example.com>",
    )
    assert [r.addr for r in ctx.to] == ["alice@example.com", "carol@example.com"]
    assert [r.addr for r in ctx.cc] == ["dave@example.com"]
    assert ctx.warning is None


def test_reply_context_prefers_reply_to_over_sender() -> None:
    ctx = _ctx(original_reply_to="Alice Work <alice@work.example>")
    assert [r.addr for r in ctx.to] == ["alice@work.example"]


def test_reply_context_prefixes_re_once() -> None:
    assert _ctx(original_subject="Hello").subject == "Re: Hello"
    assert _ctx(original_subject="RE: Hello").subject == "RE: Hello"
    assert _ctx(original_subject="re: Hello").subject == "re: Hello"


def test_reply_context_threads_intact_headers_with_thread_id() -> None:
    ctx = _ctx(
        rfc_message_id="<orig@example.com>",
        references="<root@example.com>",
        in_reply_to="<root@example.com>",
    )
    assert ctx.in_reply_to == "<orig@example.com>"
    assert ctx.references == "<root@example.com> <orig@example.com>"
    assert ctx.thread_id == "t1"


def test_reply_context_intact_headers_without_references_use_in_reply_to() -> None:
    ctx = _ctx(rfc_message_id="<orig@x>", in_reply_to="<prev@x>")
    assert ctx.references == "<prev@x> <orig@x>"


def test_reply_context_intact_thread_starter_references_only_itself() -> None:
    ctx = _ctx(rfc_message_id="<orig@x>")
    assert ctx.in_reply_to == "<orig@x>"
    assert ctx.references == "<orig@x>"


def test_reply_context_manual_forward_uses_wrapper_headers_without_thread_id() -> None:
    ctx = _ctx(
        rfc_message_id=None,
        in_reply_to="<orig@acme.example>",
        references="<root@acme.example> <orig@acme.example>",
        original_sender="Acme <billing@acme.example>",
    )
    assert [r.addr for r in ctx.to] == ["billing@acme.example"]
    assert ctx.in_reply_to == "<orig@acme.example>"
    assert ctx.references == "<root@acme.example> <orig@acme.example>"
    assert ctx.thread_id is None


def test_reply_context_manual_forward_without_wrapper_headers_has_no_threading() -> None:
    ctx = _ctx(rfc_message_id=None)
    assert ctx.in_reply_to is None
    assert ctx.references is None
    assert ctx.thread_id is None


def test_reply_context_falls_back_to_sender_when_everyone_is_filtered() -> None:
    ctx = _ctx(original_sender="Jimmy <jimmy@example.com>", original_to="hermes@example.com")
    assert [r.addr for r in ctx.to] == ["jimmy@example.com"]
    assert ctx.cc == []


def test_reply_context_drops_bad_header_entries_into_warning() -> None:
    ctx = _ctx(original_to="Jörg <jörg@example.com>, Carol <carol@example.com>")
    assert [r.addr for r in ctx.to] == ["alice@example.com", "carol@example.com"]
    assert ctx.warning is not None
    assert "jörg@example.com" in ctx.warning


def test_reply_context_fails_when_no_recipient_is_usable() -> None:
    with pytest.raises(MailError, match="no usable reply recipient"):
        _ctx(original_sender="Jörg <jörg@example.com>")


def test_reply_context_keeps_comma_names_quoted_for_rendering() -> None:
    ctx = _ctx(original_sender='"Larsson, Jimmy" <jl@example.com>')
    rendered = ctx.to[0].render()
    assert rendered == '"Larsson, Jimmy" <jl@example.com>'
    assert parse_recipients([rendered]) == [Recipient("Larsson, Jimmy", "jl@example.com")]


def test_create_draft_posts_raw_and_thread_id(mock_gmail_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {
        "id": "d1",
        "message": {"id": "m9", "threadId": "t1", "labelIds": ["DRAFT"]},
    }
    mock_gmail_service.users().drafts().create.return_value = call

    ref = create_draft(
        mock_gmail_service,
        to=[Recipient("Alice", "alice@example.com")],
        subject="Re: Hello",
        body="Hi",
        thread_id="t1",
    )
    assert ref == DraftRef(
        draft_id="d1",
        message_id="m9",
        thread_id="t1",
        to=["Alice <alice@example.com>"],
        cc=[],
        subject="Re: Hello",
        warning=None,
    )
    _, kwargs = mock_gmail_service.users().drafts().create.call_args
    assert kwargs["userId"] == "me"
    assert kwargs["body"]["message"]["threadId"] == "t1"
    assert _decode(kwargs["body"]["message"]["raw"])["Subject"] == "Re: Hello"


def test_create_draft_omits_thread_id_when_none(mock_gmail_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {"id": "d1", "message": {"id": "m9", "threadId": "t-new"}}
    mock_gmail_service.users().drafts().create.return_value = call

    ref = create_draft(mock_gmail_service, to=[Recipient("", "a@x.com")], subject="s", body="b")
    assert ref.thread_id == "t-new"
    _, kwargs = mock_gmail_service.users().drafts().create.call_args
    assert "threadId" not in kwargs["body"]["message"]


def test_create_draft_malformed_response_raises(mock_gmail_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {"id": "d1"}
    mock_gmail_service.users().drafts().create.return_value = call
    with pytest.raises(MailError, match="unexpected draft response"):
        create_draft(mock_gmail_service, to=[Recipient("", "a@x.com")], subject="s", body="b")


def test_create_draft_reports_api_reason(mock_gmail_service: MagicMock) -> None:
    resp = httplib2.Response({"status": 403, "reason": "Forbidden"})
    content = b'{"error": {"code": 403, "message": "Insufficient Permission"}}'
    call = MagicMock()
    call.execute.side_effect = HttpError(resp, content, uri="u")
    mock_gmail_service.users().drafts().create.return_value = call
    with pytest.raises(MailError, match="create draft failed: HTTP 403 Insufficient Permission"):
        create_draft(mock_gmail_service, to=[Recipient("", "a@x.com")], subject="s", body="b")


def test_delete_draft_calls_gmail(mock_gmail_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = ""
    mock_gmail_service.users().drafts().delete.return_value = call
    delete_draft(mock_gmail_service, draft_id="d1")
    _, kwargs = mock_gmail_service.users().drafts().delete.call_args
    assert kwargs == {"userId": "me", "id": "d1"}


def test_delete_draft_reports_api_reason(mock_gmail_service: MagicMock) -> None:
    resp = httplib2.Response({"status": 404, "reason": "Not Found"})
    content = b'{"error": {"code": 404, "message": "Requested entity was not found."}}'
    call = MagicMock()
    call.execute.side_effect = HttpError(resp, content, uri="u")
    mock_gmail_service.users().drafts().delete.return_value = call
    with pytest.raises(MailError, match="delete draft d1 failed: HTTP 404"):
        delete_draft(mock_gmail_service, draft_id="d1")


def _stored_draft(mock_gmail_service: MagicMock, tmp_path: Path) -> MagicMock:
    txt = tmp_path / "a.txt"
    txt.write_bytes(b"one")
    raw = build_draft_raw(
        to=[Recipient("Alice", "alice@example.com")],
        cc=[Recipient("", "bob@example.com")],
        subject="Re: Hello",
        body="old body",
        attachments=[txt],
        in_reply_to="<orig@example.com>",
        references="<root@example.com> <orig@example.com>",
    )
    get_call = MagicMock()
    get_call.execute.return_value = {
        "id": "d1",
        "message": {"id": "m1", "threadId": "t1", "raw": raw},
    }
    mock_gmail_service.users().drafts().get.return_value = get_call
    update_call = MagicMock()
    update_call.execute.return_value = {"id": "d1", "message": {"id": "m2", "threadId": "t1"}}
    mock_gmail_service.users().drafts().update.return_value = update_call
    return update_call


def _updated_message(mock_gmail_service: MagicMock) -> tuple[EmailMessage, dict]:
    _, kwargs = mock_gmail_service.users().drafts().update.call_args
    return _decode(kwargs["body"]["message"]["raw"]), kwargs


def test_update_draft_changes_body_and_keeps_everything_else(
    mock_gmail_service: MagicMock, tmp_path: Path
) -> None:
    _stored_draft(mock_gmail_service, tmp_path)

    ref = update_draft(mock_gmail_service, draft_id="d1", body="new body")

    assert ref.draft_id == "d1"
    assert ref.message_id == "m2"
    assert ref.to == ["Alice <alice@example.com>"]
    assert ref.cc == ["bob@example.com"]
    assert ref.subject == "Re: Hello"
    _, get_kwargs = mock_gmail_service.users().drafts().get.call_args
    assert get_kwargs == {"userId": "me", "id": "d1", "format": "raw"}
    msg, kwargs = _updated_message(mock_gmail_service)
    assert kwargs["userId"] == "me"
    assert kwargs["id"] == "d1"
    assert kwargs["body"]["message"]["threadId"] == "t1"
    assert [a.addr_spec for a in msg["To"].addresses] == ["alice@example.com"]
    assert [a.addr_spec for a in msg["Cc"].addresses] == ["bob@example.com"]
    assert msg["Subject"] == "Re: Hello"
    assert msg["In-Reply-To"] == "<orig@example.com>"
    assert msg["References"] == "<root@example.com> <orig@example.com>"
    assert msg.get_body(preferencelist=("plain",)).get_content() == "new body\n"
    assert [(p.get_filename(), p.get_payload(decode=True)) for p in msg.iter_attachments()] == [
        ("a.txt", b"one")
    ]


def test_update_draft_empty_cc_clears_cc(mock_gmail_service: MagicMock, tmp_path: Path) -> None:
    _stored_draft(mock_gmail_service, tmp_path)
    ref = update_draft(mock_gmail_service, draft_id="d1", cc=[])
    assert ref.cc == []
    msg, _ = _updated_message(mock_gmail_service)
    assert "Cc" not in msg


def test_update_draft_empty_attachments_removes_all(
    mock_gmail_service: MagicMock, tmp_path: Path
) -> None:
    _stored_draft(mock_gmail_service, tmp_path)
    update_draft(mock_gmail_service, draft_id="d1", attachments=[])
    msg, _ = _updated_message(mock_gmail_service)
    assert list(msg.iter_attachments()) == []
    assert msg.get_body(preferencelist=("plain",)).get_content() == "old body\n"


def test_update_draft_new_attachments_replace_stored_ones(
    mock_gmail_service: MagicMock, tmp_path: Path
) -> None:
    _stored_draft(mock_gmail_service, tmp_path)
    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(b"%PDF two")
    update_draft(mock_gmail_service, draft_id="d1", attachments=[pdf])
    msg, _ = _updated_message(mock_gmail_service)
    assert [p.get_filename() for p in msg.iter_attachments()] == ["b.pdf"]


def test_update_draft_replaces_recipients_and_subject(
    mock_gmail_service: MagicMock, tmp_path: Path
) -> None:
    _stored_draft(mock_gmail_service, tmp_path)
    ref = update_draft(
        mock_gmail_service,
        draft_id="d1",
        to=[Recipient("Carol", "carol@example.com")],
        subject="Re: Hello again",
    )
    assert ref.to == ["Carol <carol@example.com>"]
    assert ref.cc == ["bob@example.com"]
    msg, _ = _updated_message(mock_gmail_service)
    assert [a.addr_spec for a in msg["To"].addresses] == ["carol@example.com"]
    assert msg["Subject"] == "Re: Hello again"


def test_update_draft_with_nothing_to_change_raises(mock_gmail_service: MagicMock) -> None:
    with pytest.raises(MailError, match="nothing to update"):
        update_draft(mock_gmail_service, draft_id="d1")
    mock_gmail_service.users().drafts().get.assert_not_called()


def test_update_draft_malformed_get_response_raises(mock_gmail_service: MagicMock) -> None:
    get_call = MagicMock()
    get_call.execute.return_value = {"id": "d1", "threadId": "t1", "raw": "abc"}
    mock_gmail_service.users().drafts().get.return_value = get_call
    with pytest.raises(MailError, match="unexpected draft response"):
        update_draft(mock_gmail_service, draft_id="d1", body="x")


def test_update_draft_reports_api_reason_on_fetch(mock_gmail_service: MagicMock) -> None:
    resp = httplib2.Response({"status": 404, "reason": "Not Found"})
    content = b'{"error": {"code": 404, "message": "Requested entity was not found."}}'
    get_call = MagicMock()
    get_call.execute.side_effect = HttpError(resp, content, uri="u")
    mock_gmail_service.users().drafts().get.return_value = get_call
    with pytest.raises(MailError, match="fetch draft d1 failed: HTTP 404"):
        update_draft(mock_gmail_service, draft_id="d1", body="x")
