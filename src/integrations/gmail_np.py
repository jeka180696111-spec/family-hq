"""Gmail polling for Nova Poshta notifications.

Background job reads unread emails from Nova Poshta, extracts the TTN
from subject/body, and pipes it into the existing parcel tracking
flow. Closes the loop the user wants: posylka auto-appears in chat
without anyone copying the number.

Why Gmail instead of NP API: NP's public API returns only parcels you
sent (as Recipient there's no list endpoint). Forwarded SMS/email is
the documented workaround used by most Telegram-bot trackers.

Requires GMAIL_USER + GOOGLE_OAUTH_REFRESH_TOKEN with gmail.readonly
scope (the existing refresh token works if you ran the OAuth setup
with both Drive AND Gmail scopes).
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import structlog

log = structlog.get_logger()


_TTN_RE = re.compile(r"\b(\d{14})\b")
_NP_SENDERS = (
    "novaposhta", "nova-poshta", "novaposhta.ua", "nova_poshta",
    "noreply@novaposhta", "info@novaposhta",
)


def _build_service(settings: Any):
    """Return a Gmail v1 service authenticated via the same OAuth refresh
    token that backs DriveClient. Re-uses creds to avoid asking the user
    to run a second OAuth flow."""
    from google.oauth2.credentials import Credentials as UserCredentials
    from googleapiclient.discovery import build
    cid = getattr(settings, "google_oauth_client_id", "")
    csec = getattr(settings, "google_oauth_client_secret", "")
    rtok = getattr(settings, "google_oauth_refresh_token", "")
    if not (cid and csec and rtok):
        return None
    creds = UserCredentials(
        token=None,
        refresh_token=rtok,
        client_id=cid,
        client_secret=csec,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=[
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/gmail.modify",
        ],
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _extract_ttn(text: str) -> list[str]:
    """Pull 14-digit TTNs from a message — subject + body decoded."""
    if not text:
        return []
    return list(dict.fromkeys(_TTN_RE.findall(text)))


def _list_unread_np(service) -> list[str]:
    """Return Gmail message IDs of unread NP messages, last 7 days."""
    # newer_than:7d UNREAD from NP domain
    q = (
        "is:unread newer_than:7d "
        "(from:novaposhta.ua OR from:novaposhta OR subject:nova OR subject:пошта OR subject:ТТН)"
    )
    res = service.users().messages().list(userId="me", q=q, maxResults=30).execute()
    return [m["id"] for m in (res.get("messages") or [])]


def _read_message(service, msg_id: str) -> str:
    """Fetch a message and return subject + decoded body concatenated."""
    import base64
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    payload = msg.get("payload") or {}
    headers = {h["name"].lower(): h["value"] for h in (payload.get("headers") or [])}
    subject = headers.get("subject", "")
    sender = headers.get("from", "").lower()
    if not any(s in sender for s in _NP_SENDERS):
        return ""
    # Walk parts to find text/plain or text/html
    body_text = ""
    parts = payload.get("parts") or [payload]
    stack = list(parts)
    while stack:
        p = stack.pop()
        if p.get("parts"):
            stack.extend(p["parts"])
            continue
        data = ((p.get("body") or {}).get("data")) or ""
        mime = p.get("mimeType", "")
        if data and (mime.startswith("text/") or mime == "text/plain"):
            try:
                body_text += "\n" + base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="ignore")
            except Exception:
                pass
    return subject + "\n" + body_text


def _mark_read(service, msg_id: str) -> None:
    try:
        service.users().messages().modify(
            userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]},
        ).execute()
    except Exception:
        log.exception("gmail_mark_read_failed", msg_id=msg_id)


async def poll_np_emails(memory: Any, agents: dict, settings: Any) -> None:
    try:
        loop = asyncio.get_event_loop()
        service = await loop.run_in_executor(None, _build_service, settings)
        if not service:
            return
        ids = await loop.run_in_executor(None, _list_unread_np, service)
        if not ids:
            return
        devops_agent = agents.get("devops")
        for msg_id in ids:
            try:
                text = await loop.run_in_executor(None, _read_message, service, msg_id)
                if not text:
                    continue
                ttns = _extract_ttn(text)
                if not ttns:
                    continue
                # Detect recipient from text — marina mentioned?
                t_lower = text.lower()
                if "марин" in t_lower or "марина" in t_lower or "marina" in t_lower:
                    member = "marina"
                else:
                    member = "eugene"
                for ttn in ttns:
                    if devops_agent:
                        try:
                            await devops_agent._parcel_track(
                                ttn=ttn, title="", member=member,
                            )
                            log.info("gmail_np_tracked", ttn=ttn, member=member)
                        except Exception:
                            log.exception("gmail_np_track_failed", ttn=ttn)
                await loop.run_in_executor(None, _mark_read, service, msg_id)
            except Exception:
                log.exception("gmail_np_poll_msg_failed", msg_id=msg_id)
    except Exception:
        log.exception("gmail_np_poll_failed")


def register_gmail_np_poll_job(scheduler, memory, agents, settings) -> None:
    if not (getattr(settings, "google_oauth_refresh_token", "")
            and getattr(settings, "google_oauth_client_id", "")):
        log.info("gmail_np_poll_skipped_no_oauth")
        return
    scheduler.add_job(
        poll_np_emails, "interval", minutes=15,
        args=[memory, agents, settings],
        id="gmail_np_poll", replace_existing=True,
    )
    log.info("gmail_np_poll_registered")
