# NFL Calendar

Self-contained container that downloads the nflverse schedule, produces `nfl.ics` every six hours, and serves it through NGINX Proxy Manager. It does not contact Google or any third-party account.

```text
nflverse games.csv → Python container → /nfl.ics → NGINX Proxy Manager → Google Calendar
```

## Source and limitations

The free source is `https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv`. It is a structured, versioned CSV with no HTML to scrape, but **it is not an official NFL API**. All dependency on its format is isolated in [source.py](nfl_calendar/source.py). The CSV provides `game_id`, season, phase, week, teams, venue, stadium, and kickoff time.

A timezone-aware `start_time` is preserved as the same UTC instant. Otherwise, `gametime` is interpreted in nflverse's documented timezone (`America/New_York`), with no stadium, city, or team mapping. A `TBD` game is omitted until an usable kickoff is published.

`DTEND` always prioritizes `end_time`, then `duration`, then `EVENT_DURATION_FALLBACK_MINUTES=210`. nflverse currently does not provide official end times, which is a known limitation; no game-specific estimate is made. A future official NFL source only needs to be added in `source.py`.

## Docker and NGINX Proxy Manager

```bash
NFL_SEASON=2026 docker compose up -d --build
```

The container runs as its built-in non-root user. It stores the generated calendar in `/tmp/nfl.ics` and refreshes every six hours (`SYNC_INTERVAL_SECONDS=21600`). The file is intentionally not persisted: after a container restart, `/healthz` returns 503 until the next successful nflverse download. It exposes:

- `GET /nfl.ics` — `text/calendar; charset=utf-8`, cached for 5 minutes;
- `GET /healthz` — returns 200 once a valid calendar is available.

In NGINX Proxy Manager, create a Proxy Host for `calendar.mondomaine.fr` with **Forward Scheme: `http`**, host `nfl-calendar` (when it shares a Docker network with NPM), and port `8000`. Configure HTTPS only in NPM's **SSL** tab for the public side, then use `https://calendar.mondomaine.fr/nfl.ics`. Sending HTTPS directly to port 8000 is incorrect and produces TLS/HTTP 400 logs. If NPM is on a separate Docker network, attach both containers to a shared Docker network; do not add an nginx configuration to this project.

In Google Calendar: **Other calendars → + → From URL → `https://calendar.mondomaine.fr/nfl.ics`**. Google chooses its own refresh interval.

## Local use

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m nfl_calendar.cli --season 2026 --dry-run
python -m nfl_calendar.cli --season 2026 --output output/nfl.ics
pytest
```

Environment variables: `NFL_SEASON`, `OUTPUT_FILE`, `EVENT_DURATION_FALLBACK_MINUTES`, `NFLVERSE_URL`, `CALENDAR_DOMAIN`, `LOG_LEVEL`, `SYNC_INTERVAL_SECONDS`, and `PORT`.

The CLI validates the data and ICS, writes with a temporary file + `fsync` + atomic replacement, keeps the old file on errors, and skips identical output. The UID is always `nfl-<game_id>@<CALENDAR_DOMAIN>`: a date, kickoff, stadium, or `DTEND` change updates the existing event.

## Tests and troubleshooting

`pytest` covers parsing, UIDs, TBD games, `DTEND` priority, ICS generation, atomic writes, changes, HTTP errors/timeouts, and the embedded HTTP server. Network failures and empty or invalid CSV responses keep the last served calendar.

The [Postman collection](postman/nflcalendar.postman_collection.json) verifies the URL published by NGINX Proxy Manager.
