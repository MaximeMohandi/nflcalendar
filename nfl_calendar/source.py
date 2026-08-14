"""The only module aware of the remote NFL.com and nflverse formats."""
from __future__ import annotations

import csv
import html
import io
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import Game

LOG = logging.getLogger(__name__)
NFLVERSE_GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
NFL_SCHEDULE_URL = "https://www.nfl.com/schedules"
HEADERS = {"User-Agent": "nfl-calendar/1.0 (+https://calendar.mondomaine.fr)"}


class SourceError(RuntimeError):
    pass


NFL_EVENT = re.compile(
    r'"homeTeam":\{.*?"fullName":"(?P<home>[^"]+)"\},"awayTeam":\{.*?"fullName":"(?P<away>[^"]+)"\}.*?'
    r'"time":"(?P<time>[^"]+)".*?"venue":\{.*?"name":"(?P<stadium>[^"]+)".*?"city":"(?P<city>[^"]+)".*?'
    r'"season":(?P<season>\d+),"seasonType":"(?P<phase>[^"]+)","status":"(?P<status>[^"]+)","week":(?P<week>\d+).*?'
    r'"externalIds":\[(?P<ids>.*?)\]',
)
GSIS_ID = re.compile(r'"source":"gsis","id":"(?P<id>[^"]+)"')


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


def parse_nfl_schedule_page(text: str, season: int) -> list[Game]:
    """Parse NFL.com's serialized Next.js schedule payload, isolated from the rest of the app."""
    payload = html.unescape(text).replace(r'\"', '"')
    games = []
    for match in NFL_EVENT.finditer(payload):
        if int(match["season"]) != season:
            continue
        game_id = GSIS_ID.search(match["ids"])
        if not game_id:
            continue
        games.append(Game(
            game_id=game_id["id"], start_time=_timestamp(match["time"]), away_team=match["away"], home_team=match["home"],
            status=match["status"], stadium=match["stadium"], city=match["city"], week=match["week"], phase=match["phase"],
        ))
    return games


def download_nfl_schedule(season: int, session: requests.Session) -> list[Game]:
    """Fetch NFL.com's weekly pages; their payload contains all published phases."""
    try:
        index = session.get(NFL_SCHEDULE_URL, timeout=15)
        index.raise_for_status()
        slugs = sorted(set(re.findall(r'/schedules/' + str(season) + r'/by-week/([a-z0-9-]+)', html.unescape(index.text))))
        pages = [session.get(f"{NFL_SCHEDULE_URL}/{season}/by-week/{slug}", timeout=15) for slug in slugs]
        for page in pages:
            page.raise_for_status()
    except requests.RequestException as error:
        raise SourceError(f"NFL.com schedule download failed: {error}") from error
    games = {game.game_id: game for page in pages for game in parse_nfl_schedule_page(page.text, season)}
    if not games:
        raise SourceError("NFL.com schedule contains no games")
    LOG.info("Found %d official NFL games", len(games))
    return list(games.values())


def download_games(season: int, url: str = NFLVERSE_GAMES_URL, timeout: float = 15, session: requests.Session | None = None) -> list[Game]:
    LOG.info("Downloading NFL schedule")
    client = session or _session()
    try:
        return download_nfl_schedule(season, client)
    except SourceError as error:
        LOG.warning("NFL.com schedule unavailable; using nflverse fallback: %s", error)
    try:
        response = client.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as error:
        raise SourceError(f"NFL schedule download failed: {error}") from error
    games = parse_games(response.text, season)
    LOG.info("Found %d nflverse fallback games", len(games))
    return games
