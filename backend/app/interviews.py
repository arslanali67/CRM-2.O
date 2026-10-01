"""M20: interviews. Zone-safe times, in-app reminders (DB function, run by the worker), .ics export.

A time is entered as a local date/time plus the IANA zone it was agreed in, stored as a UTC instant plus
that zone. Local times that do not exist (DST gap) or happen twice (DST overlap) are refused, never guessed.
Recording an interview moves its opportunity to 'interviewing' through M19's fact path. Nothing here sends email.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from app import settings
from app.deps import audit, get_db, require_owner
from app.opportunities import record_fact

router = APIRouter(dependencies=[Depends(require_owner)])

Kind = Literal["video", "phone", "onsite"]
Status = Literal["scheduled", "done", "cancelled"]
ZONES = available_timezones()


class InterviewIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    local_start: datetime  # naive local date/time, e.g. "2026-10-06T10:00"
    time_zone: str = Field(max_length=64)
    duration_minutes: int = Field(60, ge=5, le=600)
    kind: Kind = "video"
    location: str = Field("", max_length=500)
    interviewers: str = Field("", max_length=500)
    notes: str = Field("", max_length=4000)


class StatusIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    status: Status
    outcome: str = Field("", max_length=2000)


def to_utc(local: datetime, zone: str) -> datetime:
    """The exact instant of a wall-clock time in a zone; refuses DST gaps and overlaps."""
    if zone not in ZONES:
        raise HTTPException(422, f"Unknown time zone {zone!r}; use an IANA name like Europe/Berlin")
    try:
        tz = ZoneInfo(zone)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, f"Unknown time zone {zone!r}") from None
    naive = local.replace(tzinfo=None, second=0, microsecond=0)
    early, late = naive.replace(tzinfo=tz, fold=0), naive.replace(tzinfo=tz, fold=1)
    if early.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != naive:
        raise HTTPException(422, f"{naive:%Y-%m-%d %H:%M} does not exist in {zone} (the clocks skip that hour); "
                                 "pick another time")
    if early.utcoffset() != late.utcoffset():
        raise HTTPException(422, f"{naive:%Y-%m-%d %H:%M} happens twice in {zone} (the clocks go back); "
                                 "pick a time outside that hour")
    return early.astimezone(timezone.utc)


UNSAFE_SCHEME = re.compile(r"^\s*(javascript|data|vbscript|file)\s*:", re.I)


def check_location(location: str) -> None:
    """A link must be http(s); an address like 'Room: 3' stays allowed. The database enforces the same."""
    if UNSAFE_SCHEME.match(location) or ("://" in location and not location.lower().startswith(("http://", "https://"))):
        raise HTTPException(422, "Meeting links must start with http:// or https://")


def shape(row: dict) -> dict:
    local = row["starts_at"].astimezone(ZoneInfo(row["time_zone"]))
    return {**row, "local_start": local.strftime("%Y-%m-%dT%H:%M"),
            "local_label": f"{local:%a %d %b %Y, %H:%M} ({row['time_zone']})",
            "ends_at": row["starts_at"] + timedelta(minutes=row["duration_minutes"]),
            "upcoming": row["status"] == "scheduled" and row["starts_at"] > datetime.now(timezone.utc)}


SELECT = ("SELECT i.*, o.title AS opportunity_title, o.company_id, c.name AS company_name FROM interviews i "
          "JOIN opportunities o ON o.id = i.opportunity_id JOIN companies c ON c.id = o.company_id ")


def load(conn, interview_id: int) -> dict:
    row = conn.execute(SELECT + "WHERE i.id = %s", (interview_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Interview not found")
    return row


@router.get("/interview-zones")
def zones():
    return sorted(ZONES)


@router.get("/opportunities/{opportunity_id}/interviews")
def for_opportunity(opportunity_id: int, conn=Depends(get_db, scope="function")):
    return [shape(r) for r in conn.execute(SELECT + "WHERE i.opportunity_id = %s ORDER BY i.starts_at",
                                           (opportunity_id,)).fetchall()]


@router.post("/opportunities/{opportunity_id}/interviews", status_code=201)
def create(opportunity_id: int, body: InterviewIn, conn=Depends(get_db, scope="function")):
    if not conn.execute("SELECT 1 FROM opportunities WHERE id = %s", (opportunity_id,)).fetchone():
        raise HTTPException(404, "Opportunity not found")
    check_location(body.location)
    starts = to_utc(body.local_start, body.time_zone)
    data = body.model_dump(exclude={"local_start"})
    iid = conn.execute(
        "INSERT INTO interviews (opportunity_id, title, starts_at, time_zone, duration_minutes, kind, location, "
        "interviewers, notes) VALUES (%(opp)s, %(title)s, %(starts)s, %(time_zone)s, %(duration_minutes)s, %(kind)s, "
        "%(location)s, %(interviewers)s, %(notes)s) RETURNING id", {**data, "opp": opportunity_id, "starts": starts},
    ).fetchone()["id"]
    moved = record_fact(conn, opportunity_id, "interviewing", f"interview recorded: {body.title}")
    audit(conn, "interview.created", "interview", iid, {"opportunity_id": opportunity_id, "title": body.title,
                                                        "starts_at": starts.isoformat(), "time_zone": body.time_zone,
                                                        "stage_moved": moved})
    return shape(load(conn, iid))


@router.get("/interviews")
def listing(when: Literal["upcoming", "past", "all"] = "upcoming", conn=Depends(get_db, scope="function")):
    where = {"upcoming": "i.status = 'scheduled' AND i.starts_at > now() ORDER BY i.starts_at",
             "past": "NOT (i.status = 'scheduled' AND i.starts_at > now()) ORDER BY i.starts_at DESC",
             "all": "TRUE ORDER BY i.starts_at DESC"}[when]
    return [shape(r) for r in conn.execute(SELECT + "WHERE " + where + " LIMIT 500").fetchall()]


@router.get("/interviews/{interview_id}")
def detail(interview_id: int, conn=Depends(get_db, scope="function")):
    return shape(load(conn, interview_id))


@router.put("/interviews/{interview_id}")
def edit(interview_id: int, body: InterviewIn, conn=Depends(get_db, scope="function")):
    old = load(conn, interview_id)
    check_location(body.location)
    starts = to_utc(body.local_start, body.time_zone)
    conn.execute(
        "UPDATE interviews SET title = %(title)s, starts_at = %(starts)s, time_zone = %(time_zone)s, "
        "duration_minutes = %(duration_minutes)s, kind = %(kind)s, location = %(location)s, "
        "interviewers = %(interviewers)s, notes = %(notes)s, sequence = sequence + 1, updated_at = now() "
        "WHERE id = %(id)s", {**body.model_dump(exclude={"local_start"}), "starts": starts, "id": interview_id})
    audit(conn, "interview.updated", "interview", interview_id,
          {"title": body.title, "from": old["starts_at"].isoformat(), "to": starts.isoformat(), "time_zone": body.time_zone})
    return shape(load(conn, interview_id))


@router.post("/interviews/{interview_id}/status")
def set_status(interview_id: int, body: StatusIn, conn=Depends(get_db, scope="function")):
    old = load(conn, interview_id)
    conn.execute("UPDATE interviews SET status = %s, outcome = %s, sequence = sequence + 1, updated_at = now() "
                 "WHERE id = %s", (body.status, body.outcome, interview_id))
    audit(conn, f"interview.{body.status}", "interview", interview_id,
          {"title": old["title"], "from": old["status"], "outcome": body.outcome})
    return shape(load(conn, interview_id))


@router.get("/opportunities/{opportunity_id}/interview-suggestion")
def suggestion(opportunity_id: int, conn=Depends(get_db, scope="function")):
    """An interview date the AI found (with verified evidence) in this opportunity's replies. Prefill only."""
    o = conn.execute("SELECT * FROM opportunities WHERE id = %s", (opportunity_id,)).fetchone()
    if not o:
        raise HTTPException(404, "Opportunity not found")
    rows = conn.execute(
        "SELECT a.extracted, m.id AS inbound_message_id FROM ai_analyses a JOIN inbound_messages m "
        "ON m.id = a.inbound_message_id WHERE a.status = 'ok' AND m.company_id = %s AND m.label = 'reply' "
        "AND (m.id = %s OR m.received_at >= %s) ORDER BY m.received_at DESC NULLS LAST, m.id DESC",
        (o["company_id"], o["inbound_message_id"], o["created_at"])).fetchall()
    for r in rows:
        for d in (r["extracted"] or {}).get("dates", []):
            try:
                local = datetime.fromisoformat(d.get("iso", ""))
            except ValueError:
                continue
            if d.get("purpose") == "interview" and local.tzinfo is None:
                return {"local_start": local.strftime("%Y-%m-%dT%H:%M"), "text": d.get("text", ""),
                        "evidence": d.get("evidence", ""), "inbound_message_id": r["inbound_message_id"]}
    return None


# ---------- .ics ----------

def ics_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def fold(line: str) -> str:
    """RFC 5545: lines longer than 75 octets continue on the next line after a space (never inside a UTF-8 char)."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode()
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode())
            cur = b""
        cur += b
    out.append(cur.decode())
    return "\r\n ".join(out)


def ics(row: dict) -> str:
    utc = "%Y%m%dT%H%M%SZ"
    desc = "\n".join(x for x in (f"Company: {row['company_name']}", f"Opportunity: {row['opportunity_title']}",
                                  row["interviewers"] and f"Interviewers: {row['interviewers']}",
                                  f"Agreed time: {shape(row)['local_label']}", row["notes"]) if x)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Job Outreach CRM//Interviews//EN", "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH", "BEGIN:VEVENT",
        f"UID:interview-{row['id']}@job-outreach-crm.local",
        f"SEQUENCE:{row['sequence']}",
        f"DTSTAMP:{datetime.now(timezone.utc):{utc}}",
        f"DTSTART:{row['starts_at'].astimezone(timezone.utc):{utc}}",
        f"DTEND:{(row['starts_at'] + timedelta(minutes=row['duration_minutes'])).astimezone(timezone.utc):{utc}}",
        f"SUMMARY:{ics_text(row['title'] + ' – ' + row['company_name'])}",
        f"DESCRIPTION:{ics_text(desc)}",
        f"STATUS:{'CANCELLED' if row['status'] == 'cancelled' else 'CONFIRMED'}",
    ]
    if row["location"]:
        lines.append(f"LOCATION:{ics_text(row['location'])}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(fold(line) for line in lines) + "\r\n"


@router.get("/interviews/{interview_id}/calendar.ics")
def download_ics(interview_id: int, conn=Depends(get_db, scope="function")):
    row = load(conn, interview_id)
    return Response(ics(row), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="interview-{interview_id}.ics"'})


# ---------- reminders (worker) ----------

def reminders_tick() -> dict:
    with psycopg.connect(settings.DATABASE_URL, row_factory=dict_row) as conn:
        n = conn.execute("SELECT interview_reminders() AS n").fetchone()["n"]
    return {"action": "reminders", "created": n}
