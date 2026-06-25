"""Google Calendar integration for Family HQ."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials
from pydantic import BaseModel
import structlog

log = structlog.get_logger()

_SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarEvent(BaseModel):
    """A Google Calendar event."""

    event_id: str
    title: str
    start: datetime
    end: datetime | None
    description: str = ""
    location: str = ""


class CalendarClient:
    """
    Google Calendar client.

    All blocking Google API calls are run in a thread executor so the
    async event loop is never blocked.
    """

    def __init__(self, service_account_info: dict, calendar_id: str) -> None:
        self._sa_info = service_account_info
        self._calendar_id = calendar_id
        self._service = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_service(self):
        """Build a fresh Calendar API service (sync). Used both for
        lazy init and to recover after a broken connection."""
        creds = Credentials.from_service_account_info(
            self._sa_info, scopes=_SCOPES
        )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    async def _get_service(self):
        """Lazy-init Calendar API service in a thread executor."""
        if self._service is not None:
            return self._service
        self._service = await self._run_sync(self._build_service)
        log.info("calendar_service_initialized")
        return self._service

    async def _run_sync(self, func, *args, **kwargs):
        """Run a blocking API call in the default thread executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    @staticmethod
    def _parse_event(raw: dict[str, Any]) -> CalendarEvent:
        """Convert a raw API event dict into a CalendarEvent."""
        start_raw = raw.get("start", {})
        end_raw = raw.get("end", {})

        def _parse_dt(d: dict) -> datetime | None:
            if not d:
                return None
            if "dateTime" in d:
                dt = datetime.fromisoformat(d["dateTime"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            if "date" in d:
                # All-day events: return midnight UTC
                return datetime.strptime(d["date"], "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            return None

        start = _parse_dt(start_raw) or datetime.now(timezone.utc)
        end = _parse_dt(end_raw)

        return CalendarEvent(
            event_id=raw["id"],
            title=raw.get("summary", ""),
            start=start,
            end=end,
            description=raw.get("description", ""),
            location=raw.get("location", ""),
        )

    @staticmethod
    def _dt_to_body(dt: datetime | None, default_end: datetime | None = None) -> dict:
        """Produce an API-compatible start/end body fragment."""
        if dt is None:
            return {}
        # Naive datetime (no tzinfo) is treated as Kyiv local time — that's
        # what the agent passes when the user says 'today at 23:00'.
        if dt.tzinfo is None:
            from src.utils.time import KYIV_TZ
            dt = dt.replace(tzinfo=KYIV_TZ)
        return {"dateTime": dt.isoformat(), "timeZone": "Europe/Kyiv"}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime | None = None,
        description: str = "",
        location: str = "",
        color_id: str | None = None,
    ) -> CalendarEvent:
        """Create a new calendar event and return it.

        color_id values (Google Calendar):
          1=Lavender 2=Sage 3=Grape(purple) 4=Flamingo(red)
          5=Banana(yellow) 6=Tangerine(orange) 7=Peacock(cyan)
          8=Graphite(gray) 9=Blueberry(blue) 10=Basil(green) 11=Tomato(red-dark)
        """
        svc = await self._get_service()

        if end is None:
            end = start + timedelta(hours=1)

        body: dict[str, Any] = {
            "summary": title,
            "description": description,
            "location": location,
            "start": self._dt_to_body(start),
            "end": self._dt_to_body(end),
        }
        if color_id:
            body["colorId"] = str(color_id)

        def _create():
            # Retry once on transient socket errors — Google API
            # connections sometimes drop mid-request (BrokenPipe,
            # ConnectionReset). A single immediate retry recovers.
            import socket, ssl
            try:
                return (
                    svc.events()
                    .insert(calendarId=self._calendar_id, body=body)
                    .execute()
                )
            except (BrokenPipeError, ConnectionResetError, socket.error, ssl.SSLError):
                log.warning("calendar_create_retry")
                # Rebuild service to get a fresh connection
                self._service = None
                fresh = self._build_service()
                return (
                    fresh.events()
                    .insert(calendarId=self._calendar_id, body=body)
                    .execute()
                )

        raw = await self._run_sync(_create)
        event = self._parse_event(raw)
        log.info(
            "calendar_event_created",
            event_id=event.event_id,
            title=title,
            start=start.isoformat(),
        )
        return event

    async def list_recent(self, days_back: int = 3) -> list[CalendarEvent]:
        """List events that started within the last *days_back* days."""
        svc = await self._get_service()
        now = datetime.now(timezone.utc)
        time_min = now - timedelta(days=days_back)

        def _list():
            return (
                svc.events()
                .list(
                    calendarId=self._calendar_id,
                    timeMin=time_min.isoformat(),
                    timeMax=now.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
                )
                .execute()
            )

        result = await self._run_sync(_list)
        events = [self._parse_event(e) for e in result.get("items", [])]
        log.debug("calendar_list_recent", days_back=days_back, returned=len(events))
        return events

    async def list_upcoming(self, days: int = 7) -> list[CalendarEvent]:
        """List events starting now and within the next *days* days."""
        svc = await self._get_service()

        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days)

        def _list():
            return (
                svc.events()
                .list(
                    calendarId=self._calendar_id,
                    timeMin=now.isoformat(),
                    timeMax=time_max.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
                )
                .execute()
            )

        result = await self._run_sync(_list)
        events = [self._parse_event(e) for e in result.get("items", [])]
        log.debug("calendar_list_upcoming", days=days, returned=len(events))
        return events

    async def delete_event(self, event_id: str) -> bool:
        """Delete an event. Returns ``True`` if deleted, ``False`` if not found."""
        svc = await self._get_service()

        def _delete():
            svc.events().delete(
                calendarId=self._calendar_id, eventId=event_id
            ).execute()

        try:
            await self._run_sync(_delete)
            log.info("calendar_event_deleted", event_id=event_id)
            return True
        except HttpError as exc:
            if exc.resp.status == 404:
                log.warning("calendar_event_not_found", event_id=event_id)
                return False
            log.error(
                "calendar_delete_error",
                event_id=event_id,
                status=exc.resp.status,
                error=str(exc),
            )
            raise

    async def find_events(self, query: str) -> list[CalendarEvent]:
        """Search events by free-text query across the whole calendar."""
        svc = await self._get_service()

        def _search():
            return (
                svc.events()
                .list(
                    calendarId=self._calendar_id,
                    q=query,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                )
                .execute()
            )

        result = await self._run_sync(_search)
        events = [self._parse_event(e) for e in result.get("items", [])]
        log.debug("calendar_find_events", query=query, returned=len(events))
        return events
