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
