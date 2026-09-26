"""Select a player's Best 50 from their personal bests."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable

from . import rating
from .tachi import PBBundle

# (old-song slots, new-song slots)
SLOTS = {
    "maimai": (35, 15),
    "chunithm": (30, 20),
}

LAMP_SHORT = {
    "ALL PERFECT+": "AP+",
    "ALL PERFECT": "AP",
    "FULL COMBO+": "FC+",
    "FULL COMBO": "FC",
    "ALL JUSTICE CRITICAL": "AJC",
    "ALL JUSTICE": "AJ",
}


@dataclass
class Entry:
    game: str
    title: str
    difficulty: str
    level: str
    level_const: float
    score: float  # maimai: achievement %, chunithm: score
    rank: str
    lamp: str | None
    rating: Fraction
    is_new: bool

    @property
    def score_text(self) -> str:
        if self.game == "maimai":
            return f"{self.score:.4f}%"
        return f"{int(self.score):,}"

    @property
    def rating_text(self) -> str:
        if self.game == "maimai":
            return str(int(self.rating))
        return f"{float(self.rating):.2f}"


@dataclass
class B50:
    game: str
    username: str
    old: list[Entry]
    new: list[Entry]

    @property
    def old_sum(self) -> Fraction:
        return sum((e.rating for e in self.old), Fraction(0))

    @property
    def new_sum(self) -> Fraction:
        return sum((e.rating for e in self.new), Fraction(0))

    @property
    def total(self) -> Fraction:
        """In-game player rating derived from the B50."""
        s = self.old_sum + self.new_sum
        if self.game == "chunithm":
            return rating.truncate(s / 50)
        return s

    def total_text(self) -> str:
        t = self.total
        return f"{float(t):.2f}" if self.game == "chunithm" else str(int(t))

    def average_text(self, entries: list[Entry]) -> str:
        if not entries:
            return "-"
        avg = sum((e.rating for e in entries), Fraction(0)) / len(entries)
        return f"{float(avg):.2f}"


def _pick_lamp(score_data: dict) -> str | None:
    # Newer Tachi splits CHUNITHM lamps into noteLamp/clearLamp.
    for key in ("lamp", "noteLamp"):
        lamp = score_data.get(key)
        if lamp and lamp in LAMP_SHORT:
            return LAMP_SHORT[lamp]
    return None


def build_entries(game: str, bundle: PBBundle, new_versions: Iterable[str]) -> list[Entry]:
    new_set = {v.strip().lower() for v in new_versions if v.strip()}
    entries: list[Entry] = []
    for pb in bundle.pbs:
        chart = bundle.charts.get(pb.chart_id)
        if chart is None:
            continue
        song = bundle.songs.get(chart.song_id)
        title = song.title if song else "?"

        if game == "maimai":
            percent = pb.score_data.get("percent")
            if percent is None:
                continue
            score: float = float(percent)
            r = Fraction(rating.maimai_rating(chart.level_const, score))
            rank = rating.maimai_rank(score)
        else:
            raw = pb.score_data.get("score")
            if raw is None:
                continue
            score = int(raw)
            r = rating.chunithm_rating(chart.level_const, score)
            rank = rating.chunithm_rank(score)

        entries.append(
            Entry(
                game=game,
                title=title,
                difficulty=chart.difficulty,
                level=chart.level,
                level_const=chart.level_const,
                score=score,
                rank=rank,
                lamp=_pick_lamp(pb.score_data),
                rating=r,
                is_new=chart.display_version.strip().lower() in new_set,
            )
        )
    return entries


def build_b50(game: str, bundle: PBBundle, new_versions: Iterable[str]) -> B50:
    entries = build_entries(game, bundle, new_versions)
    key = lambda e: (e.rating, e.level_const, e.score)  # noqa: E731
    old_slots, new_slots = SLOTS[game]
    old = sorted((e for e in entries if not e.is_new), key=key, reverse=True)[:old_slots]
    new = sorted((e for e in entries if e.is_new), key=key, reverse=True)[:new_slots]
    return B50(game=game, username=bundle.username, old=old, new=new)
