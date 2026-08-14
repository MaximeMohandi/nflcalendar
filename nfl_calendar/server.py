"""Small HTTP server and in-container schedule loop for nginx-proxy-manager."""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from wsgiref.simple_server import make_server

from .source import SourceError
from .sync import refresh

LOG = logging.getLogger(__name__)


def application(output: Path):
    def app(environ, start_response):
        if environ["PATH_INFO"] == "/healthz":
            status, body = ("200 OK", b"ok\n") if output.exists() else ("503 Service Unavailable", b"calendar unavailable\n")
            start_response(status, [("Content-Type", "text/plain; charset=utf-8")])
            return [body]
        if environ["PATH_INFO"] == "/nfl.ics" and output.exists():
            body = output.read_bytes()
            start_response("200 OK", [("Content-Type", "text/calendar; charset=utf-8"), ("Cache-Control", "public, max-age=300"), ("Content-Length", str(len(body)))])
            return [body]
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"not found\n"]
    return app


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    season = int(os.environ["NFL_SEASON"])
    output = Path(os.getenv("OUTPUT_FILE", "/tmp/nfl.ics"))
    fallback = int(os.getenv("EVENT_DURATION_FALLBACK_MINUTES", "210"))
    domain = os.getenv("CALENDAR_DOMAIN", "calendar.mondomaine.fr")
    source_url = os.getenv("NFLVERSE_URL", "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv")
    interval = int(os.getenv("SYNC_INTERVAL_SECONDS", "21600"))

    def sync_forever():
        while True:
            try:
                changed, games, tbd, official_ends = refresh(season, output, fallback, domain, source_url)
                LOG.info("Sync complete: %d games, %d TBD, %d official ends, changed=%s", games, tbd, official_ends, changed)
            except (SourceError, ValueError, OSError) as error:
                LOG.error("Keeping previous calendar: %s", error)
            threading.Event().wait(interval)

    threading.Thread(target=sync_forever, daemon=True).start()
    with make_server("0.0.0.0", int(os.getenv("PORT", "8000")), application(output)) as server:
        LOG.info("Serving /nfl.ics on port %s", os.getenv("PORT", "8000"))
        server.serve_forever()


if __name__ == "__main__":
    main()
