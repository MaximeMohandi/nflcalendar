from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from icalendar import Calendar
import requests

from nfl_calendar.calendar import event_end, make_calendar, uid, validate_games, write_calendar
from nfl_calendar.models import Game
from nfl_calendar.source import SourceError, download_games, parse_games
from nfl_calendar.server import application

FIXTURE = (Path(__file__).parent / "fixtures" / "games.csv").read_text()
START = datetime(2026, 9, 14, 0, 20, tzinfo=timezone.utc)


def games():
    return parse_games(FIXTURE, 2026)


def test_parse_nflverse_game_and_official_kickoff_is_unchanged():
    game = games()[0]
    assert game.game_id == "2026091400"
    assert game.start_time == START
    assert game.away_team == "DAL"
    assert game.home_team == "PHI"


def test_uid_is_stable_when_game_details_change():
    original = games()[0]
    changed = Game(original.game_id, START + timedelta(hours=1), "DAL", "PHI", stadium="New stadium")
    assert uid(original, "calendar.example") == uid(changed, "calendar.example")


def test_official_end_duration_and_fallback_priority():
    start_only, official_end, official_duration, _ = games()
    assert event_end(official_end, 210) == datetime(2026, 9, 14, 3, 42, tzinfo=timezone.utc)
    assert event_end(official_duration, 210) == datetime(2026, 9, 14, 3, 41, tzinfo=timezone.utc)
    assert event_end(start_only, 210) == datetime(2026, 9, 14, 3, 50, tzinfo=timezone.utc)


def test_official_end_replaces_estimate_without_changing_uid():
    estimated = Game("same", START, "DAL", "PHI")
    corrected = Game("same", START, "DAL", "PHI", end_time=datetime(2026, 9, 14, 3, 42, tzinfo=timezone.utc))
    assert uid(estimated, "calendar.example") == uid(corrected, "calendar.example")
    assert event_end(estimated, 210) != event_end(corrected, 210)


def test_tbd_game_is_not_published_but_is_accepted():
    payload = make_calendar(games(), 210, "calendar.example")
    events = list(Calendar.from_ical(payload).walk("VEVENT"))
    assert len(events) == 3
    assert all("2026091403" not in str(event["UID"]) for event in events)


def test_ics_is_parseable_and_has_required_fields():
    event = list(Calendar.from_ical(make_calendar(games(), 210, "calendar.example")).walk("VEVENT"))[0]
    assert {"UID", "DTSTAMP", "DTSTART", "DTEND", "SUMMARY", "DESCRIPTION", "LOCATION", "STATUS"} <= set(event.keys())


def test_duplicate_ids_and_invalid_end_are_rejected():
    game = games()[0]
    with pytest.raises(ValueError, match="Duplicate"):
        validate_games([game, game], 210)
    with pytest.raises(ValueError, match="Invalid end"):
        validate_games([Game("bad", START, "A", "B", end_time=START)], 210)


def test_atomic_write_skips_identical_content_and_keeps_old_file_on_failed_generation(tmp_path):
    output = tmp_path / "nfl.ics"
    first = make_calendar(games(), 210, "calendar.example")
    assert write_calendar(output, first)
    assert not write_calendar(output, first)
    previous = output.read_bytes()
    with pytest.raises(ValueError):
        make_calendar([], 210, "calendar.example")
    assert output.read_bytes() == previous


def test_changed_kickoff_and_end_are_detected_in_logs(tmp_path, caplog):
    output = tmp_path / "nfl.ics"
    original = Game("same", START, "DAL", "PHI")
    corrected = Game("same", START + timedelta(hours=1), "DAL", "PHI", end_time=datetime(2026, 9, 14, 4, 42, tzinfo=timezone.utc))
    write_calendar(output, make_calendar([original], 210, "calendar.example"))
    with caplog.at_level("INFO"):
        assert write_calendar(output, make_calendar([corrected], 210, "calendar.example"))
    assert "Kickoff changed" in caplog.text
    assert "End time changed" in caplog.text


def test_empty_or_incomplete_source_is_rejected():
    with pytest.raises(SourceError, match="empty"):
        parse_games("", 2026)
    with pytest.raises(SourceError, match="without id or teams"):
        parse_games("game_id,season,away_team,home_team\n,2026,A,B\n", 2026)


@pytest.mark.parametrize("error", [requests.Timeout("timed out"), requests.HTTPError("503")])
def test_http_failures_are_reported(error):
    class FailedSession:
        def get(self, *_args, **_kwargs):
            raise error

    with pytest.raises(SourceError, match="download failed"):
        download_games(2026, session=FailedSession())


def test_http_server_serves_published_calendar(tmp_path):
    output = tmp_path / "nfl.ics"
    output.write_bytes(make_calendar([games()[0]], 210, "calendar.example"))
    response = []
    body = b"".join(application(output)({"PATH_INFO": "/nfl.ics"}, lambda status, headers: response.extend((status, headers))))
    assert response[0] == "200 OK"
    assert dict(response[1])["Content-Type"].startswith("text/calendar")
    assert b"BEGIN:VCALENDAR" in body
