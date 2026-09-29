"""Select a player's Best 50 from their personal bests."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Iterable

from . import rating
from .net_parsers import ChunithmRecord, MaimaiRecord, PlayerInfo
from .songdb import SongDB, level_to_min_const

# (old-song slots, new-song slots)
SLOTS = {
    "maimai": (35, 15),
    "chunithm": (30, 20),
}

# Played for fun, never rated: CHUNITHM WORLD'S END and maimai 宴 (UTAGE) charts.
UNRATED = ("WORLD'S END", "UTAGE")


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
    # chunithm: music id; maimai: (title, genre). Used to find the jacket.
    song_key: object = None
    jacket_path: str | None = None

    @property
    def score_text(self) -> str:
        if self.game == "maimai":
            return f"{self.score:.4f}%"
        return f"{int(self.score):,}"

    @property
    def rated(self) -> bool:
        return self.difficulty not in UNRATED

    @property
    def rating_text(self) -> str:
        if not self.rated:
            return "-"
        if self.game == "maimai":
            return str(int(self.rating))
        return f"{float(self.rating):.2f}"


@dataclass
class B50:
    game: str
    username: str
    old: list[Entry]
    new: list[Entry]
    # Rating shown on the official site, when the data came from there.
    official_rating: str | None = None
    source: str = ""
    title: str | None = None
    title_rarity: str | None = None
    icon: bytes | None = None  # image data
    plate: bytes | None = None
    level: str | None = None
    # every played chart's best score {(title, difficulty): score}, when the site gave them all (maimai)
    played: dict[tuple[str, str], float] = field(default_factory=dict, repr=False)
    # charts in the player's region, by difficulty, for the difficulties whose record pages were read:
    # {difficulty: {music id (CHUNITHM) / title (maimai)}}. None when unknown.
    available: dict[str, set] | None = field(default=None, repr=False)

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


def make_entry(
    game: str,
    title: str,
    difficulty: str,
    level: str,
    level_const: float,
    score: float,
    lamp: str | None,
    is_new: bool,
    song_key: object = None,
) -> Entry:
    if game == "maimai":
        score = float(score)
        r = Fraction(rating.maimai_rating(level_const, score))
        rank = rating.maimai_rank(score)
    else:
        score = int(score)
        r = rating.chunithm_rating(level_const, score)
        rank = rating.chunithm_rank(score)
    if difficulty in UNRATED:
        r = Fraction(0)
    return Entry(
        game=game,
        title=title,
        difficulty=difficulty,
        level=level,
        level_const=level_const,
        score=score,
        rank=rank,
        lamp=lamp,
        rating=r,
        is_new=is_new,
        song_key=song_key,
    )


def _is_new(display_version: str, new_versions: Iterable[str]) -> bool:
    return display_version.strip().lower() in {v.strip().lower() for v in new_versions if v.strip()}


def _sort_key(e: Entry):
    return (e.rating, e.level_const, e.score)


def select_b50(game: str, username: str, entries: list[Entry], **kwargs) -> B50:
    old_slots, new_slots = SLOTS[game]
    old = sorted((e for e in entries if not e.is_new), key=_sort_key, reverse=True)[:old_slots]
    new = sorted((e for e in entries if e.is_new), key=_sort_key, reverse=True)[:new_slots]
    return B50(game=game, username=username, old=old, new=new, **kwargs)


def b50_from_chunithm_net(
    player: PlayerInfo,
    best: list[ChunithmRecord],
    new: list[ChunithmRecord],
    songdb: SongDB,
) -> B50:
    """CHUNITHM-NET already lists the exact Best 30 / New 20; we only add constants."""

    def convert(records: list[ChunithmRecord], is_new: bool) -> list[Entry]:
        out = []
        for r in records:
            info = songdb.chunithm_chart(r.idx, r.difficulty)
            level = info.level if info else "?"
            const = info.level_const if info else 0.0
            out.append(make_entry("chunithm", r.title, r.difficulty, level, const, r.score, r.lamp, is_new, r.idx))
        return sorted(out, key=_sort_key, reverse=True)

    return B50(
        game="chunithm",
        username=player.name,
        old=convert(best, False),
        new=convert(new, True),
        official_rating=player.rating,
        source="CHUNITHM-NET",
        title=player.title,
        title_rarity=player.title_rarity,
        level=player.level,
    )


def b50_from_maimai_net(
    player: PlayerInfo,
    records: list[MaimaiRecord],
    songdb: SongDB,
    new_versions: Iterable[str],
) -> B50:
    new_versions = list(new_versions)
    entries = []
    for r in records:
        info = songdb.maimai_chart(r.title, r.difficulty, r.genre)
        if info is not None:
            const, level, is_new = info.level_const, info.level, _is_new(info.display_version, new_versions)
        else:
            # Unknown chart (probably brand new): estimate from the displayed level.
            const, level, is_new = level_to_min_const(r.level, "maimai"), r.level, True
        entries.append(
            make_entry("maimai", r.title, r.difficulty, level, const, r.achievement, r.lamp, is_new, (r.title, r.genre))
        )
    return select_b50(
        "maimai", player.name, entries, official_rating=player.rating, source="maimai DX NET",
        title=player.title, title_rarity=player.title_rarity
    )
