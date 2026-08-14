from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from .source import NFLVERSE_GAMES_URL, SourceError
from .sync import refresh


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an NFL iCalendar file")
    parser.add_argument("--season", type=int, default=int(os.getenv("NFL_SEASON", "0")) or None)
    parser.add_argument("--output", type=Path, default=Path(os.getenv("OUTPUT_FILE", "output/nfl.ics")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    args = parser.parse_args()
    if not args.season:
        parser.error("--season or NFL_SEASON is required")
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s")
    fallback = int(os.getenv("EVENT_DURATION_FALLBACK_MINUTES", "210"))
    try:
        source_url = os.getenv("NFLVERSE_URL", NFLVERSE_GAMES_URL)
        if args.dry_run:
            from .source import download_games
            from .calendar import make_calendar
            games = download_games(args.season, source_url)
            payload = make_calendar(games, fallback, os.getenv("CALENDAR_DOMAIN", "calendar.mondomaine.fr"))
        else:
            changed, count, tbd, official_end = refresh(args.season, args.output, fallback, os.getenv("CALENDAR_DOMAIN", "calendar.mondomaine.fr"), source_url)
    except (SourceError, ValueError) as error:
        logging.error("Keeping previous calendar: %s", error)
        return 1
    if args.dry_run:
        tbd = sum(game.start_time is None for game in games)
        official_end = sum(game.end_time is not None for game in games)
        logging.info("Season: %s | Games: %d | TBD: %d | Official ends: %d | ICS size: %d bytes", args.season, len(games), tbd, official_end, len(payload))
    else:
        logging.info("Season: %s | Games: %d | TBD: %d | Official ends: %d | changed=%s", args.season, count, tbd, official_end, changed)
    if args.dry_run:
        logging.info("Dry run successful.")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
