from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

from icalendar import Calendar, Event

from .models import Game

LOG = logging.getLogger(__name__)


def event_end(game: Game, fallback_minutes: int) -> datetime | None:
    if game.start_time is None:
        return None
    return game.end_time or (game.start_time + (game.duration or timedelta(minutes=fallback_minutes)))


def uid(game: Game, domain: str) -> str:
    return f"nfl-{game.game_id}@{domain}"


def _status(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.lower()
    return {"scheduled": "CONFIRMED", "in progress": "CONFIRMED", "final": "CONFIRMED", "postponed": "TENTATIVE", "cancelled": "CANCELLED"}.get(normalized)


def validate_games(games: list[Game], fallback_minutes: int) -> None:
    if not 1 <= len(games) <= 400:
        raise ValueError(f"Unreasonable game count: {len(games)}")
    ids = [game.game_id for game in games]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate game id")
    for game in games:
        if not game.away_team or not game.home_team:
            raise ValueError(f"Missing teams for {game.game_id}")
        end = event_end(game, fallback_minutes)
        if end and game.start_time and end <= game.start_time:
            raise ValueError(f"Invalid end time for {game.game_id}")


def make_calendar(games: list[Game], fallback_minutes: int, domain: str) -> bytes:
    validate_games(games, fallback_minutes)
    calendar = Calendar()
    calendar.add("prodid", "-//nfl-calendar//EN")
    calendar.add("version", "2.0")
    for game in games:
        if game.start_time is None:  # TBD kickoff: publish only when NFL provides a real time.
            continue
        event = Event()
        event.add("uid", uid(game, domain))
        # Stable DTSTAMP avoids rewriting an unchanged subscribed calendar.
        event.add("dtstamp", game.start_time)
        event.add("dtstart", game.start_time)
        if end := event_end(game, fallback_minutes):
            event.add("dtend", end)
        event.add("summary", game.summary)
        description = "NFL"
        if game.week:
            description += f" - Week {game.week}"
        if game.phase:
            description += f" ({game.phase})"
        event.add("description", description)
        if game.stadium or game.city:
            event.add("location", ", ".join(value for value in (game.stadium, game.city) if value))
        if status := _status(game.status):
            event.add("status", status)
        calendar.add_component(event)
    payload = calendar.to_ical()
    Calendar.from_ical(payload)  # Reject malformed output before publication.
    return payload


def _event_map(payload: bytes) -> dict[str, Event]:
    return {str(event["UID"]): event for event in Calendar.from_ical(payload).walk("VEVENT")}


def _log_changes(old: bytes, new: bytes) -> None:
    try:
        previous, current = _event_map(old), _event_map(new)
    except ValueError:
        return
    changed = [key for key in current if key not in previous or current[key].to_ical() != previous[key].to_ical()]
    LOG.info("Schedule updated: %d events changed", len(changed))
    for key in changed[:5]:
        LOG.info("Changed event: %s", key)
        if key not in previous:
            continue
        for field, label in (("DTSTART", "Kickoff"), ("DTEND", "End time"), ("LOCATION", "Venue")):
            before, after = previous[key].get(field), current[key].get(field)
            if before != after:
                LOG.info("%s changed: %s -> %s", label, before, after)


def write_calendar(path: Path, payload: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_bytes() if path.exists() else None
    if old == payload:
        LOG.info("No schedule changes detected.")
        return False
    if old:
        _log_changes(old, payload)
    with NamedTemporaryFile("wb", dir=path.parent, prefix=f"{path.name}.", suffix=".tmp", delete=False) as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    os.replace(temporary, path)
    LOG.info("Generated %s successfully", path)
    return True
