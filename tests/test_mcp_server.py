"""Tests for mcp_server.py — shape of instructions block, tool registration."""
from __future__ import annotations

from unittest.mock import MagicMock


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

    mocker.patch.object(
        mcp_server, "_get_credentials", side_effect=AuthError("missing")
    )
    result = mcp_server.auth_status()
    assert result["valid"] is False
    assert "missing" in result["error"]


def test_auth_status_config_error(mocker) -> None:
    from hermes_google import mcp_server
    from hermes_google.core.config import ConfigError

    mocker.patch.object(
        mcp_server, "_get_credentials", side_effect=ConfigError("bad config")
    )
    result = mcp_server.auth_status()
    assert result["valid"] is False
    assert "bad config" in result["error"]


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
            PendingMessage(
                id="m1", thread_id="t", sender="s", subject="x", date="d", snippet="..."
            )
        ],
    )
    result = mcp_server.mail_list_pending(limit=5)
    assert result == [
        {"id": "m1", "thread_id": "t", "sender": "s", "subject": "x", "date": "d",
         "snippet": "..."}
    ]


def test_mail_send_draft_tool_passes_user_email(mocker) -> None:
    from hermes_google import mcp_server

    fake_services = MagicMock()
    mocker.patch.object(mcp_server, "_get_services", return_value=fake_services)
    cfg = MagicMock(user_email="jimmy@example.com")
    mocker.patch.object(mcp_server, "_get_config", return_value=cfg)
    send_spy = mocker.patch.object(mcp_server.mail_core, "send_draft", return_value="sent-1")

    result = mcp_server.mail_send_draft(
        to="jimmy@example.com", subject="s", body="b"
    )
    assert result == {"id": "sent-1"}
    _, kwargs = send_spy.call_args
    assert kwargs["user_email"] == "jimmy@example.com"
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
            original_sender="s",
            original_subject="x",
            original_body="b",
            in_reply_to=None,
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
    result = mcp_server.cal_list_events(
        calendar="user", start="s", end="e"
    )
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
