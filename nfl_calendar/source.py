"""The only module aware of nflverse's remote CSV format."""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import Game

LOG = logging.getLogger(__name__)
NFLVERSE_GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
HEADERS = {"User-Agent": "nfl-calendar/1.0 (+https://calendar.mondomaine.fr)"}


class SourceError(RuntimeError):
    pass


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SourceError("NFL timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _duration(value: str | None) -> timedelta | None:
    if not value:
        return None
    try:
        return timedelta(minutes=float(value))
    except ValueError as error:
        raise SourceError(f"Unsupported duration {value!r}") from error


def _kickoff(row: dict[str, str]) -> datetime | None:
    if row.get("start_time"):
        return _timestamp(row["start_time"])
    if not row.get("gameday") or not row.get("gametime") or row["gametime"].upper() == "TBD":
        return None
    try:
        # nflverse's games.csv documents gametime in US Eastern time.
        local = datetime.fromisoformat(f"{row['gameday']}T{row['gametime']}")
        return local.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    except ValueError as error:
        raise SourceError(f"Invalid kickoff for {row.get('game_id')}") from error


def parse_games(text: str, season: int) -> list[Game]:
    if not text.strip():
        raise SourceError("NFL schedule response is empty")
    try:
        rows = csv.DictReader(io.StringIO(text))
        games = []
        for row in rows:
            if row.get("season") != str(season):
                continue
            game_id, away, home = row.get("game_id"), row.get("away_team"), row.get("home_team")
            if not game_id or not away or not home:
                raise SourceError("NFL schedule contains a game without id or teams")
            games.append(Game(
                game_id=game_id,
                start_time=_kickoff(row),
                end_time=_timestamp(row["end_time"]) if row.get("end_time") else None,
                duration=_duration(row.get("duration") or row.get("duration_minutes")),
                away_team=away,
                home_team=home,
                status=row.get("status") or None,
                stadium=row.get("stadium") or None,
                city=row.get("location") or row.get("city") or None,
                week=row.get("week") or None,
                phase=row.get("game_type") or row.get("phase") or None,
            ))
    except csv.Error as error:
        raise SourceError("Invalid NFL schedule CSV") from error
    if not games:
        raise SourceError(f"No games found for season {season}")
    return games


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(total=2, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def download_games(season: int, url: str = NFLVERSE_GAMES_URL, timeout: float = 15, session: requests.Session | None = None) -> list[Game]:
    LOG.info("Downloading NFL schedule")
    try:
        response = (session or _session()).get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as error:
        raise SourceError(f"NFL schedule download failed: {error}") from error
    games = parse_games(response.text, season)
    LOG.info("Found %d games", len(games))
    return games
