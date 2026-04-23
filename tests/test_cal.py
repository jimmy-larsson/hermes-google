"""Tests for cal.py — Calendar core operations."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hermes_google.core.cal import (
    CalendarError,
    CalendarRef,
    EventSummary,
    create_event,
    delete_event,
    list_calendars,
    list_events,
    resolve_calendar_id,
    update_event,
)


def test_resolve_calendar_id_aliases() -> None:
    assert resolve_calendar_id("hermes") == "primary"
    # 'user' is resolved via config caller, so pass the mapping in
    assert resolve_calendar_id("user", user_calendar_id="jimmy@example.com") == "jimmy@example.com"
    # Concrete IDs pass through
    assert resolve_calendar_id("abc@group.calendar.google.com") == "abc@group.calendar.google.com"


def test_resolve_calendar_id_user_without_mapping_raises() -> None:
    with pytest.raises(CalendarError, match="user calendar not configured"):
        resolve_calendar_id("user")


def test_list_calendars(mock_calendar_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {
        "items": [
            {"id": "primary", "summary": "Hermes", "accessRole": "owner"},
            {"id": "jimmy@example.com", "summary": "Jimmy", "accessRole": "writer"},
        ]
    }
    mock_calendar_service.calendarList().list.return_value = call

    result = list_calendars(mock_calendar_service)
    assert len(result) == 2
    assert isinstance(result[0], CalendarRef)
    assert result[0].id == "primary"
    assert result[1].access_role == "writer"


def test_list_events(mock_calendar_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {
        "items": [
            {
                "id": "e1",
                "summary": "Lunch",
                "start": {"dateTime": "2026-04-24T12:30:00+09:00"},
                "end": {"dateTime": "2026-04-24T13:30:00+09:00"},
                "attendees": [{"email": "a@b"}],
            }
        ]
    }
    mock_calendar_service.events().list.return_value = call

    result = list_events(
        mock_calendar_service,
        calendar_id="primary",
        time_min="2026-04-24T00:00:00+09:00",
        time_max="2026-04-25T00:00:00+09:00",
    )
    assert len(result) == 1
    assert isinstance(result[0], EventSummary)
    assert result[0].id == "e1"
    assert result[0].title == "Lunch"
    assert result[0].attendees == ["a@b"]
    _, kwargs = mock_calendar_service.events().list.call_args
    assert kwargs["calendarId"] == "primary"
    assert kwargs["singleEvents"] is True
    assert kwargs["orderBy"] == "startTime"


def test_create_event(mock_calendar_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {"id": "new-1"}
    mock_calendar_service.events().insert.return_value = call

    event_id = create_event(
        mock_calendar_service,
        calendar_id="primary",
        title="Lunch",
        start="2026-04-24T12:30:00+09:00",
        end="2026-04-24T13:30:00+09:00",
        attendees=["a@b"],
        description="with X",
    )
    assert event_id == "new-1"
    _, kwargs = mock_calendar_service.events().insert.call_args
    assert kwargs["calendarId"] == "primary"
    assert kwargs["body"]["summary"] == "Lunch"
    assert kwargs["body"]["attendees"] == [{"email": "a@b"}]
    assert kwargs["body"]["description"] == "with X"


def test_update_event_patches_fields(mock_calendar_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {"id": "e1"}
    mock_calendar_service.events().patch.return_value = call

    update_event(
        mock_calendar_service,
        calendar_id="primary",
        event_id="e1",
        fields={"start": {"dateTime": "2026-04-24T13:00:00+09:00"}},
    )
    _, kwargs = mock_calendar_service.events().patch.call_args
    assert kwargs["eventId"] == "e1"
    assert kwargs["body"] == {"start": {"dateTime": "2026-04-24T13:00:00+09:00"}}


def test_delete_event(mock_calendar_service: MagicMock) -> None:
    call = MagicMock()
    call.execute.return_value = {}
    mock_calendar_service.events().delete.return_value = call

    delete_event(mock_calendar_service, calendar_id="primary", event_id="e1")
    _, kwargs = mock_calendar_service.events().delete.call_args
    assert kwargs["eventId"] == "e1"
