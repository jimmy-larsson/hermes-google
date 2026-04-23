"""Tests for mail.py — Gmail core operations."""
from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes_google.core.mail import (
    MailError,
    PendingMessage,
    get_message,
    list_pending,
    search,
)


def _messages_list_response(ids: list[str]) -> dict:
    return {"messages": [{"id": i, "threadId": f"t-{i}"} for i in ids]}


def _build_get_side_effect(payload: dict):
    def _get(userId, id, format):  # noqa: ARG001, A002
        inner = MagicMock()
        inner.execute.return_value = payload
        return inner

    return _get


def test_list_pending_returns_unread_inbox(mock_gmail_service: MagicMock) -> None:
    # users().messages().list().execute() returns the ID list
    list_call = MagicMock()
    list_call.execute.return_value = _messages_list_response(["m1", "m2"])
    mock_gmail_service.users().messages().list.return_value = list_call

    # users().messages().get().execute() returns metadata for each ID
    def _get(userId, id, format):  # noqa: ARG001, A002
        inner = MagicMock()
        inner.execute.return_value = {
            "id": id,
            "threadId": f"t-{id}",
            "snippet": f"snippet for {id}",
            "payload": {
                "headers": [
                    {"name": "From", "value": f"sender-{id}@x"},
                    {"name": "Subject", "value": f"subj {id}"},
                    {"name": "Date", "value": "Thu, 23 Apr 2026 10:00:00 +0900"},
                ]
            },
        }
        return inner

    mock_gmail_service.users().messages().get.side_effect = _get

    result = list_pending(mock_gmail_service, limit=20)
    assert len(result) == 2
    assert isinstance(result[0], PendingMessage)
    assert result[0].id == "m1"
    assert result[0].sender == "sender-m1@x"
    assert result[0].subject == "subj m1"
    # Query must be exactly this string
    _, kwargs = mock_gmail_service.users().messages().list.call_args
    assert kwargs["q"] == "is:unread in:inbox"
    assert kwargs["userId"] == "me"


def test_list_pending_empty(mock_gmail_service: MagicMock) -> None:
    list_call = MagicMock()
    list_call.execute.return_value = {}
    mock_gmail_service.users().messages().list.return_value = list_call

    assert list_pending(mock_gmail_service, limit=20) == []


def test_search_passes_query_through(mock_gmail_service: MagicMock) -> None:
    list_call = MagicMock()
    list_call.execute.return_value = _messages_list_response(["s1"])
    mock_gmail_service.users().messages().list.return_value = list_call

    def _get(userId, id, format):  # noqa: ARG001, A002
        inner = MagicMock()
        inner.execute.return_value = {
            "id": id,
            "threadId": "t",
            "snippet": "s",
            "payload": {"headers": [
                {"name": "From", "value": "x@y"},
                {"name": "Subject", "value": "hit"},
                {"name": "Date", "value": "Thu, 23 Apr 2026 10:00:00 +0900"},
            ]},
        }
        return inner

    mock_gmail_service.users().messages().get.side_effect = _get

    result = search(mock_gmail_service, query="from:boss", limit=10)
    assert len(result) == 1
    _, kwargs = mock_gmail_service.users().messages().list.call_args
    assert kwargs["q"] == "from:boss"


def test_get_message_unwraps_forward_and_downloads_attachments(
    tmp_path: Path, mock_gmail_service: MagicMock
) -> None:
    # Raw message is a base64url-encoded .eml bytes; we fake the raw-format response.
    raw_eml = (Path(__file__).parent / "fixtures" / "fwd_plain_gmail_web.eml").read_bytes()
    raw_b64 = base64.urlsafe_b64encode(raw_eml).decode()

    get_call = MagicMock()
    get_call.execute.return_value = {"id": "m1", "threadId": "t", "raw": raw_b64}
    mock_gmail_service.users().messages().get.return_value = get_call

    detail = get_message(
        mock_gmail_service, message_id="m1", cache_dir=tmp_path
    )
    assert detail.id == "m1"
    assert detail.original_sender == "Acme Billing <billing@acme.example>"
    assert detail.original_subject == "Q1 invoice from Acme"
    assert "Please find attached" in detail.original_body
    assert detail.attachment_paths == []  # no parts in this fixture
    _, kwargs = mock_gmail_service.users().messages().get.call_args
    assert kwargs["format"] == "raw"


def test_get_message_not_found_raises(mock_gmail_service: MagicMock, tmp_path: Path) -> None:
    get_call = MagicMock()
    get_call.execute.side_effect = Exception("HttpError 404")
    mock_gmail_service.users().messages().get.return_value = get_call

    with pytest.raises(MailError):
        get_message(mock_gmail_service, message_id="nope", cache_dir=tmp_path)


def test_get_message_attachment_path_traversal_rejected(
    tmp_path: Path, mock_gmail_service: MagicMock
) -> None:
    """Traversal filename like '../../etc/passwd' must not escape cache_dir/<message_id>/."""
    # Build a minimal multipart message with a traversal-attempt filename
    msg = EmailMessage()
    msg["From"] = "attacker@evil.example"
    msg["To"] = "victim@example.com"
    msg["Subject"] = "Totally legit"
    msg["Message-ID"] = "<atk001@evil.example>"
    msg.set_content("See attachment.")
    msg.add_attachment(
        b"evil content",
        maintype="application",
        subtype="octet-stream",
        filename="../../etc/passwd",
    )

    raw_bytes = msg.as_bytes()
    raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode()

    get_call = MagicMock()
    get_call.execute.return_value = {"id": "atk1", "threadId": "t", "raw": raw_b64}
    mock_gmail_service.users().messages().get.return_value = get_call

    detail = get_message(mock_gmail_service, message_id="atk1", cache_dir=tmp_path)

    # The file must NOT exist outside cache_dir/atk1/
    escaped_path = tmp_path.parent / "etc" / "passwd"
    assert not escaped_path.exists(), "Path traversal succeeded — file written outside cache_dir"

    # Either the attachment was rejected entirely or it was written safely inside cache_dir/atk1/
    for ap in detail.attachment_paths:
        assert str(ap).startswith(str(tmp_path / "atk1")), (
            f"Attachment path {ap} is outside the expected cache_dir/message_id directory"
        )
