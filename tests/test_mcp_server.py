"""Tests for mcp_server.py — instructions, tool registration, error handling, annotations."""

from __future__ import annotations

import asyncio
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
        "mail_send_draft",  # to-enforcement
        "drive_delete",  # delete friction
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
        "mail_send_draft",
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
    destructive_tools = {"cal_delete_event", "drive_delete"}
    for tool in _tool_map().values():
        if tool.name in destructive_tools:
            assert tool.annotations is not None, f"{tool.name} missing annotations"
            assert tool.annotations.destructiveHint is True, f"{tool.name} should be destructive"


def test_idempotent_tools_annotated() -> None:
    idempotent_tools = {
        "mail_mark_read",
        "mail_archive",
        "cal_update_event",
        "drive_update",
        "drive_move",
    }
    for tool in _tool_map().values():
        if tool.name in idempotent_tools:
            assert tool.annotations is not None, f"{tool.name} missing annotations"
            assert tool.annotations.idempotentHint is True, f"{tool.name} should be idempotent"


def test_auth_status_tool_reports_validity(mocker) -> None:
    """auth_status should return a dict describing whether creds load."""
    from hermes_google import mcp_server

    fake_creds = MagicMock(valid=True, expired=False, scopes=["gmail.send"])
    mocker.patch.object(mcp_server, "_get_credentials", return_value=fake_creds)

    result = mcp_server.auth_status()
    assert result["valid"] is True
    assert result["expired"] is False
    assert "scopes" in result


def test_auth_status_missing_credentials(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.auth import AuthError

    mocker.patch.object(mcp_server, "_get_credentials", side_effect=AuthError("missing"))
    result = mcp_server.auth_status()
    assert result["valid"] is False
    assert "credentials" in result["error"]
    assert "/home" not in result["error"]


def test_auth_status_config_error(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.config import ConfigError

    mocker.patch.object(mcp_server, "_get_credentials", side_effect=ConfigError("bad config"))
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


def test_mail_send_draft_tool_calls_core(mocker) -> None:
    from hermes_google import mcp_server

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    send_spy = mocker.patch.object(mcp_server.mail_core, "send_draft", return_value="sent-1")

    result = mcp_server.mail_send_draft(to="jimmy@example.com", subject="s", body="b")
    assert result == {"id": "sent-1"}
    _, kwargs = send_spy.call_args
    assert kwargs["to"] == "jimmy@example.com"


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
