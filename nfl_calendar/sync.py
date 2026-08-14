from __future__ import annotations

from pathlib import Path

from .calendar import make_calendar, write_calendar
from .source import NFLVERSE_GAMES_URL, download_games


def refresh(season: int, output: Path, fallback_minutes: int, domain: str, source_url: str = NFLVERSE_GAMES_URL) -> tuple[bool, int, int, int]:
    games = download_games(season, source_url)
    payload = make_calendar(games, fallback_minutes, domain)
    changed = write_calendar(output, payload)
    return changed, len(games), sum(game.start_time is None for game in games), sum(game.end_time is not None for game in games)
