from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Game:
    game_id: str
    start_time: datetime | None
    away_team: str
    home_team: str
    end_time: datetime | None = None
    duration: timedelta | None = None
    status: str | None = None
    stadium: str | None = None
    city: str | None = None
    week: str | None = None
    phase: str | None = None

    @property
    def summary(self) -> str:
        return f"{self.away_team} @ {self.home_team}"

