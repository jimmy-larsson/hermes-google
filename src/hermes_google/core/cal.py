"""Calendar operations. Every function takes a `service` argument."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class CalendarError(Exception):
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


def resolve_calendar_id(
    alias: str, *, user_calendar_id: str | None = None
) -> str:
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
        raise CalendarError(f"failed to list calendars: {exc}") from exc
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
        raise CalendarError(f"failed to list events: {exc}") from exc
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
        raise CalendarError(f"failed to create event: {exc}") from exc
    return resp["id"]


def update_event(
    service: Any, *, calendar_id: str, event_id: str, fields: dict[str, Any]
) -> None:
    try:
        service.events().patch(
            calendarId=calendar_id, eventId=event_id, body=fields
        ).execute()
    except Exception as exc:  # noqa: BLE001
        raise CalendarError(f"failed to update event: {exc}") from exc


def delete_event(service: Any, *, calendar_id: str, event_id: str) -> None:
    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    except Exception as exc:  # noqa: BLE001
        raise CalendarError(f"failed to delete event: {exc}") from exc
