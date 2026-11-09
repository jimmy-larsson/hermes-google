"""Tests for mcp_server.py — instructions, tool registration, error handling, annotations."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastmcp.exceptions import ToolError


def _tool_map():
    """Return {name: FunctionTool} for the MCP server."""
    from hermes_google.mcp_server import mcp

    tools = asyncio.run(mcp.list_tools())
    return {t.name: t for t in tools}


def test_instructions_contains_key_policies() -> None:
    from hermes_google.mcp_server import INSTRUCTIONS

    required = [
        "mail_archive",  # archive policy
        "No send capability",  # drafts-only policy
        "mail_create_draft",
        "mail_create_reply_draft",
        "mail_update_draft",
        "mail_delete_draft",
        "report the returned",
        "drive_delete",  # delete friction
        "drive_rename",
        "drive_create_folder",
        "data, not instructions",  # prompt-injection note
        "confirm",  # confirmation policy
    ]
    for snippet in required:
        assert snippet in INSTRUCTIONS, f"missing policy snippet: {snippet!r}"


def test_mask_error_details_enabled() -> None:
    from hermes_google.mcp_server import mcp

    assert mcp._mask_error_details is True


def test_smoke_server_has_expected_tools() -> None:
    from hermes_google.mcp_server import mcp

    assert mcp.name == "hermes-google"
    tool_names = {t.name for t in _tool_map().values()}
    expected = {
        "auth_status",
        "mail_list_pending",
        "mail_search",
        "mail_get",
        "mail_create_draft",
        "mail_create_reply_draft",
        "mail_update_draft",
        "mail_delete_draft",
        "mail_mark_read",
        "mail_archive",
        "cal_list_calendars",
        "cal_list_events",
        "cal_create_event",
        "cal_update_event",
        "cal_delete_event",
        "drive_search",
        "drive_list",
        "drive_get",
        "drive_upload",
        "drive_update",
        "drive_move",
        "drive_rename",
        "drive_create_folder",
        "drive_delete",
    }
    assert expected == tool_names


def test_read_only_tools_annotated() -> None:
    read_only_tools = {
        "auth_status",
        "mail_list_pending",
        "mail_search",
        "mail_get",
        "cal_list_calendars",
        "cal_list_events",
        "drive_search",
        "drive_list",
        "drive_get",
    }
    for tool in _tool_map().values():
        if tool.name in read_only_tools:
            assert tool.annotations is not None, f"{tool.name} missing annotations"
            assert tool.annotations.readOnlyHint is True, f"{tool.name} should be readOnly"
            assert tool.annotations.destructiveHint is False, (
                f"{tool.name} should not be destructive"
            )


def test_destructive_tools_annotated() -> None:
    destructive_tools = {"cal_delete_event", "drive_delete", "mail_delete_draft"}
    for tool in _tool_map().values():
        if tool.name in destructive_tools:
            assert tool.annotations is not None, f"{tool.name} missing annotations"
            assert tool.annotations.destructiveHint is True, f"{tool.name} should be destructive"


def test_idempotent_tools_annotated() -> None:
    idempotent_tools = {
        "mail_mark_read",
        "mail_archive",
        "mail_update_draft",
        "cal_update_event",
        "drive_update",
        "drive_move",
        "drive_rename",
    }
    for tool in _tool_map().values():
        if tool.name in idempotent_tools:
            assert tool.annotations is not None, f"{tool.name} missing annotations"
            assert tool.annotations.idempotentHint is True, f"{tool.name} should be idempotent"


def test_auth_status_tool_reports_stored_scopes(mocker) -> None:
    from hermes_google import mcp_server

    cfg = MagicMock(credentials_path=Path("/nonexistent/token.json"))
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    fake_creds = MagicMock(valid=True, expired=False, scopes=["requested-only"])
    mocker.patch.object(mcp_server, "_get_credentials", return_value=fake_creds)
    mocker.patch.object(
        mcp_server.auth_core,
        "stored_scopes",
        return_value=["https://www.googleapis.com/auth/drive"],
    )

    result = mcp_server.auth_status()
    assert result["valid"] is True
    assert result["expired"] is False
    assert result["scopes"] == ["https://www.googleapis.com/auth/drive"]
    mcp_server.auth_core.stored_scopes.assert_called_once_with(Path("/nonexistent/token.json"))


def test_auth_status_surfaces_auth_error_text(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.auth import AuthError

    mocker.patch.object(mcp_server, "_get_config", return_value=MagicMock())
    mocker.patch.object(
        mcp_server,
        "_get_credentials",
        side_effect=AuthError("stored token lacks scopes: x; run 'hermes-google auth login'"),
    )
    result = mcp_server.auth_status()
    assert result["valid"] is False
    assert result["scopes"] == []
    assert result["error"].startswith("stored token lacks scopes: x")
    assert "/home" not in result["error"]


def test_auth_status_config_error(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.config import ConfigError

    mocker.patch.object(mcp_server, "_get_config", side_effect=ConfigError("bad config"))
    result = mcp_server.auth_status()
    assert result["valid"] is False
    assert "configuration" in result["error"]
    assert "/home" not in result["error"]


def test_reset_services_clears_cache(mocker) -> None:
    from hermes_google import mcp_server

    mcp_server._config = "sentinel_cfg"
    mcp_server._services = "sentinel_svc"
    mcp_server._reset_services()
    assert mcp_server._config is None
    assert mcp_server._services is None


def test_mail_list_pending_tool(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.mail import PendingMessage

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    mocker.patch.object(
        mcp_server.mail_core,
        "list_pending",
        return_value=[
            PendingMessage(id="m1", thread_id="t", sender="s", subject="x", date="d", snippet="...")
        ],
    )
    result = mcp_server.mail_list_pending(limit=5)
    assert result == [
        {"id": "m1", "thread_id": "t", "sender": "s", "subject": "x", "date": "d", "snippet": "..."}
    ]


def test_mail_archive_tool_calls_core(mocker) -> None:
    from hermes_google import mcp_server

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    spy = mocker.patch.object(mcp_server.mail_core, "archive")
    mcp_server.mail_archive(message_id="m1")
    _, kwargs = spy.call_args
    assert kwargs["message_id"] == "m1"


def test_mail_list_pending_clamps_limit(mocker) -> None:
    from hermes_google import mcp_server

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    spy = mocker.patch.object(mcp_server.mail_core, "list_pending", return_value=[])
    mcp_server.mail_list_pending(limit=10_000)
    _, kwargs = spy.call_args
    assert kwargs["limit"] == 100  # clamped


def test_mail_get_tool_serializes_attachment_paths(mocker, tmp_path) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.mail import MessageDetail

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    cfg = MagicMock(cache_dir=tmp_path)
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    p1 = tmp_path / "a.pdf"
    p2 = tmp_path / "b.png"
    mocker.patch.object(
        mcp_server.mail_core,
        "get_message",
        return_value=MessageDetail(
            id="m1",
            thread_id="t",
            sender="forwarder@example.com",
            original_sender="s",
            original_subject="x",
            original_body="b",
            in_reply_to=None,
            forwarding_note="Please handle this",
            attachment_paths=[p1, p2],
        ),
    )
    result = mcp_server.mail_get(message_id="m1")
    assert result["attachment_paths"] == [str(p1), str(p2)]
    # Verify Path objects were coerced to strings (JSON-serializable)
    assert all(isinstance(p, str) for p in result["attachment_paths"])


def test_cal_list_events_tool(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.cal import EventSummary

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    cfg = MagicMock(user_calendar_id="jimmy@example.com")
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    mocker.patch.object(
        mcp_server.cal_core,
        "list_events",
        return_value=[EventSummary(id="e1", title="Lunch", start="s", end="e", attendees=[])],
    )
    result = mcp_server.cal_list_events(calendar="user", start="s", end="e")
    assert result[0]["id"] == "e1"
    _, kwargs = mcp_server.cal_core.list_events.call_args
    assert kwargs["calendar_id"] == "jimmy@example.com"


def test_cal_create_event_tool(mocker) -> None:
    from hermes_google import mcp_server

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    cfg = MagicMock(user_calendar_id="jimmy@example.com")
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    mocker.patch.object(mcp_server.cal_core, "create_event", return_value="new-1")

    result = mcp_server.cal_create_event(
        calendar="hermes",
        title="Meet",
        start="2026-04-24T10:00:00+09:00",
        end="2026-04-24T11:00:00+09:00",
    )
    assert result == {"id": "new-1"}


def test_drive_search_tool(mocker, tmp_path) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drive import FileRef

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    mocker.patch.object(
        mcp_server.drive_core,
        "search",
        return_value=[FileRef(id="f1", name="n", mime_type="text/plain")],
    )
    result = mcp_server.drive_search(query="q")
    assert result[0]["id"] == "f1"


def test_drive_get_tool_returns_path(mocker, tmp_path) -> None:
    from hermes_google import mcp_server

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    cfg = MagicMock(cache_dir=tmp_path)
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    mocker.patch.object(
        mcp_server.drive_core,
        "get_file",
        return_value=tmp_path / "drive" / "f1" / "x.pdf",
    )
    result = mcp_server.drive_get(file_id="f1")
    assert result["path"].endswith("x.pdf")


def test_drive_upload_uses_default_parent(mocker, tmp_path) -> None:
    from hermes_google import mcp_server

    local = tmp_path / "x.md"
    local.write_text("hi")
    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    cfg = MagicMock(drive_default_parent_folder_id="DEFAULT")
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    spy = mocker.patch.object(mcp_server.drive_core, "upload_file", return_value="new-1")

    result = mcp_server.drive_upload(local_path=str(local), name="x.md")
    assert result == {"id": "new-1"}
    _, kwargs = spy.call_args
    assert kwargs["parent_folder_id"] == "DEFAULT"


# ---------------------------------------------------------------------------
# ToolError propagation — every domain error becomes a ToolError
# ---------------------------------------------------------------------------


def test_mail_list_pending_raises_tool_error_on_service_error(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.mail import MailError

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    mocker.patch.object(mcp_server.mail_core, "list_pending", side_effect=MailError("quota"))
    with pytest.raises(ToolError, match="quota"):
        mcp_server.mail_list_pending()


def test_mail_search_raises_tool_error_on_service_error(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.mail import MailError

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    mocker.patch.object(mcp_server.mail_core, "search", side_effect=MailError("bad query"))
    with pytest.raises(ToolError, match="bad query"):
        mcp_server.mail_search(query="x")


def test_mail_get_raises_tool_error_on_service_error(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.mail import MailError

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    cfg = MagicMock()
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    mocker.patch.object(mcp_server.mail_core, "get_message", side_effect=MailError("not found"))
    with pytest.raises(ToolError, match="not found"):
        mcp_server.mail_get(message_id="m1")


def test_cal_list_events_raises_tool_error_on_service_error(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.cal import CalendarError

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    cfg = MagicMock(user_calendar_id="u@example.com")
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    mocker.patch.object(mcp_server.cal_core, "list_events", side_effect=CalendarError("API error"))
    with pytest.raises(ToolError, match="API error"):
        mcp_server.cal_list_events(calendar="user", start="s", end="e")


def test_drive_search_raises_tool_error_on_service_error(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drive import DriveError

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    mocker.patch.object(mcp_server.drive_core, "search", side_effect=DriveError("forbidden"))
    with pytest.raises(ToolError, match="forbidden"):
        mcp_server.drive_search(query="q")


def test_drive_delete_raises_tool_error_on_service_error(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drive import DriveError

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    mocker.patch.object(mcp_server.drive_core, "delete_file", side_effect=DriveError("not found"))
    with pytest.raises(ToolError, match="not found"):
        mcp_server.drive_delete(file_id="f1")


def test_auth_error_becomes_tool_error_in_mail_tools(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.auth import AuthError

    mocker.patch.object(mcp_server, "_get_services", side_effect=AuthError("expired"))
    with pytest.raises(ToolError, match="expired"):
        mcp_server.mail_list_pending()


def test_drive_rename_tool_returns_ref(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drive import FileRef

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    spy = mocker.patch.object(
        mcp_server.drive_core,
        "rename_file",
        return_value=FileRef(id="f1", name="new.pdf", mime_type="application/pdf"),
    )
    result = mcp_server.drive_rename(file_id="f1", new_name="new.pdf")
    assert result == {"id": "f1", "name": "new.pdf", "mime_type": "application/pdf"}
    _, kwargs = spy.call_args
    assert kwargs == {"file_id": "f1", "new_name": "new.pdf"}


def test_drive_create_folder_uses_default_parent(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drive import FOLDER_MIME_TYPE, FileRef

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    cfg = MagicMock(drive_default_parent_folder_id="DEFAULT")
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    spy = mocker.patch.object(
        mcp_server.drive_core,
        "create_folder",
        return_value=FileRef(id="d1", name="SMBC pack", mime_type=FOLDER_MIME_TYPE),
    )
    result = mcp_server.drive_create_folder(name="SMBC pack")
    assert result == {
        "id": "d1",
        "name": "SMBC pack",
        "mime_type": FOLDER_MIME_TYPE,
        "parent_folder_id": "DEFAULT",
    }
    _, kwargs = spy.call_args
    assert kwargs == {"name": "SMBC pack", "parent_folder_id": "DEFAULT"}


def test_drive_create_folder_explicit_parent_wins(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drive import FOLDER_MIME_TYPE, FileRef

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    cfg = MagicMock(drive_default_parent_folder_id="DEFAULT")
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    spy = mocker.patch.object(
        mcp_server.drive_core,
        "create_folder",
        return_value=FileRef(id="d1", name="x", mime_type=FOLDER_MIME_TYPE),
    )
    result = mcp_server.drive_create_folder(name="x", parent_folder_id="P")
    assert result["parent_folder_id"] == "P"
    _, kwargs = spy.call_args
    assert kwargs["parent_folder_id"] == "P"


def test_server_has_no_send_capability() -> None:
    import inspect

    from hermes_google import mcp_server
    from hermes_google.core import drafts as drafts_core
    from hermes_google.core import mail as mail_core

    assert not hasattr(mail_core, "send_draft")
    assert not any("send" in name for name in _tool_map())
    for module in (mail_core, drafts_core, mcp_server):
        assert ".send(" not in inspect.getsource(module)


def test_mail_create_draft_tool_parses_recipients_and_paths(mocker, tmp_path) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drafts import DraftRef, Recipient

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    spy = mocker.patch.object(
        mcp_server.drafts_core,
        "create_draft",
        return_value=DraftRef(
            draft_id="d1", message_id="m1", thread_id="t1", to=["a@x.com"], cc=[], subject="s"
        ),
    )
    result = mcp_server.mail_create_draft(
        to=["a@x.com"],
        cc=['"Larsson, Jimmy" <j@x.com>'],
        subject="s",
        body="b",
        attachments=["~/file.pdf"],
    )
    assert result["draft_id"] == "d1"
    assert result["warning"] is None
    _, kwargs = spy.call_args
    assert kwargs["to"] == [Recipient("", "a@x.com")]
    assert kwargs["cc"] == [Recipient("Larsson, Jimmy", "j@x.com")]
    assert kwargs["attachments"] == [Path("~/file.pdf").expanduser().absolute()]


def test_mail_create_reply_draft_uses_config_emails_and_overrides(mocker, tmp_path) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drafts import DraftRef, Recipient, ReplyContext
    from hermes_google.core.mail import MessageDetail

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    cfg = MagicMock(
        cache_dir=tmp_path,
        user_email="jimmy@example.com",
        hermes_account_email="hermes@example.com",
    )
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    detail = MessageDetail(
        id="m1",
        thread_id="t1",
        sender="s",
        original_sender="Alice <alice@example.com>",
        original_subject="Hello",
        original_body="b",
        in_reply_to=None,
        forwarding_note=None,
        attachment_paths=[],
        rfc_message_id="<o@x>",
    )
    mocker.patch.object(mcp_server.mail_core, "get_message", return_value=detail)
    ctx = ReplyContext(
        to=[Recipient("Alice", "alice@example.com")],
        cc=[Recipient("", "bob@example.com"), Recipient("", "carol@example.com")],
        subject="Re: Hello",
        in_reply_to="<o@x>",
        references="<o@x>",
        thread_id="t1",
        warning="ignored unusable addresses: x",
    )
    ctx_spy = mocker.patch.object(mcp_server.drafts_core, "reply_context", return_value=ctx)
    create_spy = mocker.patch.object(
        mcp_server.drafts_core,
        "create_draft",
        return_value=DraftRef(
            draft_id="d1",
            message_id="m2",
            thread_id="t1",
            to=["carol@example.com"],
            cc=["bob@example.com"],
            subject="Re: Hello",
        ),
    )

    result = mcp_server.mail_create_reply_draft(
        message_id="m1", body="Hi", to=["carol@example.com"]
    )

    args, ctx_kwargs = ctx_spy.call_args
    assert args == (detail,)
    assert ctx_kwargs == {"user_email": "jimmy@example.com", "hermes_email": "hermes@example.com"}
    _, kwargs = create_spy.call_args
    assert kwargs["to"] == [Recipient("", "carol@example.com")]
    assert kwargs["cc"] == [Recipient("", "bob@example.com")]
    assert kwargs["subject"] == "Re: Hello"
    assert kwargs["in_reply_to"] == "<o@x>"
    assert kwargs["references"] == "<o@x>"
    assert kwargs["thread_id"] == "t1"
    assert result["draft_id"] == "d1"
    assert result["warning"] == "ignored unusable addresses: x"
    _, get_kwargs = mcp_server.mail_core.get_message.call_args
    assert get_kwargs["cache_dir"] is None


def test_mail_create_reply_draft_defaults_to_context_recipients(mocker, tmp_path) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drafts import DraftRef, Recipient, ReplyContext
    from hermes_google.core.mail import MessageDetail

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    cfg = MagicMock(cache_dir=tmp_path, user_email="u@x.com", hermes_account_email="h@x.com")
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    detail = MessageDetail(
        id="m1",
        thread_id="t1",
        sender="s",
        original_sender="Alice <alice@example.com>",
        original_subject="Hello",
        original_body="b",
        in_reply_to=None,
        forwarding_note=None,
        attachment_paths=[],
    )
    mocker.patch.object(mcp_server.mail_core, "get_message", return_value=detail)
    ctx = ReplyContext(
        to=[Recipient("Alice", "alice@example.com")],
        cc=[Recipient("", "bob@example.com")],
        subject="Re: Hello",
        in_reply_to=None,
        references=None,
        thread_id=None,
        warning=None,
    )
    mocker.patch.object(mcp_server.drafts_core, "reply_context", return_value=ctx)
    create_spy = mocker.patch.object(
        mcp_server.drafts_core,
        "create_draft",
        return_value=DraftRef(
            draft_id="d1", message_id="m2", thread_id="t9", to=[], cc=[], subject="Re: Hello"
        ),
    )

    mcp_server.mail_create_reply_draft(message_id="m1", body="Hi")

    _, kwargs = create_spy.call_args
    assert kwargs["to"] == ctx.to
    assert kwargs["cc"] == ctx.cc
    assert kwargs["thread_id"] is None


def _reply_setup(mocker, tmp_path, ctx):
    from hermes_google import mcp_server
    from hermes_google.core.drafts import DraftRef
    from hermes_google.core.mail import MessageDetail

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    cfg = MagicMock(cache_dir=tmp_path, user_email="u@x.com", hermes_account_email="h@x.com")
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    detail = MessageDetail(
        id="m1",
        thread_id="t1",
        sender="s",
        original_sender="Alice <alice@example.com>",
        original_subject="Hello",
        original_body="b",
        in_reply_to=None,
        forwarding_note=None,
        attachment_paths=[],
    )
    mocker.patch.object(mcp_server.mail_core, "get_message", return_value=detail)
    mocker.patch.object(mcp_server.drafts_core, "reply_context", return_value=ctx)
    return mocker.patch.object(
        mcp_server.drafts_core,
        "create_draft",
        return_value=DraftRef(
            draft_id="d1", message_id="m2", thread_id=None, to=[], cc=[], subject="Re: Hello"
        ),
    )


def _ctx_with(to, cc, warning=None):
    from hermes_google.core.drafts import ReplyContext

    return ReplyContext(
        to=to,
        cc=cc,
        subject="Re: Hello",
        in_reply_to=None,
        references=None,
        thread_id=None,
        warning=warning,
    )


def test_mail_create_reply_draft_refuses_unusable_sender_without_explicit_to(
    mocker, tmp_path
) -> None:
    from hermes_google import mcp_server

    create_spy = _reply_setup(mocker, tmp_path, _ctx_with(to=[], cc=[], warning="ignored: x"))
    with pytest.raises(ToolError, match="sender address unusable"):
        mcp_server.mail_create_reply_draft(message_id="m1", body="Hi")
    create_spy.assert_not_called()


def test_mail_create_reply_draft_explicit_to_rescues_unusable_sender(mocker, tmp_path) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drafts import Recipient

    create_spy = _reply_setup(mocker, tmp_path, _ctx_with(to=[], cc=[], warning="ignored: x"))
    result = mcp_server.mail_create_reply_draft(
        message_id="m1", body="Hi", to=["Carol <carol@example.com>"]
    )
    _, kwargs = create_spy.call_args
    assert kwargs["to"] == [Recipient("Carol", "carol@example.com")]
    assert result["warning"] == "ignored: x"


def test_mail_create_reply_draft_explicit_cc_passes_through(mocker, tmp_path) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drafts import Recipient

    create_spy = _reply_setup(
        mocker,
        tmp_path,
        _ctx_with(to=[Recipient("Alice", "alice@example.com")], cc=[Recipient("", "bob@x.com")]),
    )
    mcp_server.mail_create_reply_draft(message_id="m1", body="Hi", cc=["dave@example.com"])
    _, kwargs = create_spy.call_args
    assert kwargs["to"] == [Recipient("Alice", "alice@example.com")]
    assert kwargs["cc"] == [Recipient("", "dave@example.com")]


def test_mail_create_reply_draft_empty_cc_clears_derived_cc(mocker, tmp_path) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drafts import Recipient

    create_spy = _reply_setup(
        mocker,
        tmp_path,
        _ctx_with(to=[Recipient("Alice", "alice@example.com")], cc=[Recipient("", "bob@x.com")]),
    )
    mcp_server.mail_create_reply_draft(message_id="m1", body="Hi", cc=[])
    _, kwargs = create_spy.call_args
    assert kwargs["cc"] is None


def test_mail_update_draft_tool_passes_only_given_fields(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.drafts import DraftRef

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    spy = mocker.patch.object(
        mcp_server.drafts_core,
        "update_draft",
        return_value=DraftRef(
            draft_id="d1", message_id="m1", thread_id="t1", to=["a@x.com"], cc=[], subject="s"
        ),
    )
    result = mcp_server.mail_update_draft(draft_id="d1", body="new", cc=[])
    assert result["draft_id"] == "d1"
    _, kwargs = spy.call_args
    assert kwargs["draft_id"] == "d1"
    assert kwargs["body"] == "new"
    assert kwargs["cc"] == []
    assert kwargs["to"] is None
    assert kwargs["subject"] is None
    assert kwargs["attachments"] is None


def test_mail_delete_draft_tool_returns_id(mocker) -> None:
    from hermes_google import mcp_server

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    spy = mocker.patch.object(mcp_server.drafts_core, "delete_draft")
    assert mcp_server.mail_delete_draft(draft_id="d1") == {"draft_id": "d1"}
    _, kwargs = spy.call_args
    assert kwargs == {"draft_id": "d1"}


def test_mail_create_draft_raises_tool_error_on_service_error(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.mail import MailError

    mocker.patch.object(mcp_server, "_get_services", return_value=MagicMock())
    mocker.patch.object(
        mcp_server.drafts_core, "create_draft", side_effect=MailError("create draft failed")
    )
    with pytest.raises(ToolError, match="create draft failed"):
        mcp_server.mail_create_draft(to=["a@x.com"], subject="s", body="b")


def test_paths_expands_home_and_makes_absolute() -> None:
    from hermes_google import mcp_server

    paths = mcp_server._paths(["~unknownuser-xyz/x.pdf", "rel/y.pdf"])
    assert paths is not None
    assert all(p.is_absolute() for p in paths)
    assert str(paths[0]).endswith("~unknownuser-xyz/x.pdf")
    assert mcp_server._paths(None) is None
