"""Calendar operations. Every function takes a `service` argument."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hermes_google.core.errors import ServiceError


class CalendarError(ServiceError):
    """Raised on Calendar API failures."""


@dataclass(frozen=True)
class CalendarRef:
    id: str
    summary: str
    access_role: str


@dataclass(frozen=True)
class EventSummary:
    id: str
    title: str
    start: str
    end: str
    attendees: list[str]


def resolve_calendar_id(alias: str, *, user_calendar_id: str | None = None) -> str:
    if alias == "hermes":
        return "primary"
    if alias == "user":
        if not user_calendar_id:
            raise CalendarError("user calendar not configured (no share set up yet)")
        return user_calendar_id
    return alias


def list_calendars(service: Any) -> list[CalendarRef]:
    try:
        resp = service.calendarList().list().execute()
    except Exception as exc:  # noqa: BLE001
        raise CalendarError("failed to list calendars") from exc
    return [
        CalendarRef(id=i["id"], summary=i.get("summary", ""), access_role=i.get("accessRole", ""))
        for i in resp.get("items", [])
    ]


def _to_event(item: dict[str, Any]) -> EventSummary:
    return EventSummary(
        id=item["id"],
        title=item.get("summary", ""),
        start=item.get("start", {}).get("dateTime") or item.get("start", {}).get("date", ""),
        end=item.get("end", {}).get("dateTime") or item.get("end", {}).get("date", ""),
        attendees=[a.get("email", "") for a in item.get("attendees", [])],
    )


def list_events(
    service: Any, *, calendar_id: str, time_min: str, time_max: str
) -> list[EventSummary]:
    try:
        resp = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise CalendarError("failed to list events") from exc
    return [_to_event(i) for i in resp.get("items", [])]


def create_event(
    service: Any,
    *,
    calendar_id: str,
    title: str,
    start: str,
    end: str,
    attendees: list[str] | None = None,
    description: str | None = None,
) -> str:
    body: dict[str, Any] = {
        "summary": title,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    if description:
        body["description"] = description
    try:
        resp = service.events().insert(calendarId=calendar_id, body=body).execute()
    except Exception as exc:  # noqa: BLE001
        raise CalendarError("failed to create event") from exc
    try:
        return resp["id"]
    except KeyError as exc:
        raise CalendarError("unexpected create response format") from exc


def update_event(service: Any, *, calendar_id: str, event_id: str, fields: dict[str, Any]) -> None:
    """Patch arbitrary event fields.

    The caller (MCP tool layer) is responsible for restricting `fields` to
    user-intended keys. Core does not filter — the MCP wrapper layer
    performs the confirmation gate before invoking this function.
    """
    try:
        service.events().patch(calendarId=calendar_id, eventId=event_id, body=fields).execute()
    except Exception as exc:  # noqa: BLE001
        raise CalendarError("failed to update event") from exc


def delete_event(service: Any, *, calendar_id: str, event_id: str) -> None:
    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    except Exception as exc:  # noqa: BLE001
        raise CalendarError("failed to delete event") from exc
