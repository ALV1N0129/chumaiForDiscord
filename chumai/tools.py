"""Game logic behind the utility commands (no Discord code here, so it is easy to test)."""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from fractions import Fraction

from . import rating
from .b50 import B50, Entry, make_entry, select_b50
from .songdb import CatalogChart, CatalogSong, SongDB, normalize_title

DIFF_SHORT = {
    "BASIC": "BAS", "ADVANCED": "ADV", "EXPERT": "EXP", "MASTER": "MAS", "ULTIMA": "ULT",
    "Basic": "BAS", "Advanced": "ADV", "Expert": "EXP", "Master": "MAS", "Re:Master": "Re:MAS",
    "DX Basic": "DX BAS", "DX Advanced": "DX ADV", "DX Expert": "DX EXP", "DX Master": "DX MAS",
    "DX Re:Master": "DX Re:MAS",
}


def short(difficulty: str) -> str:
    return DIFF_SHORT.get(difficulty, difficulty)


def chart_rating(game: str, const: float, score: float) -> Fraction:
    if game == "maimai":
        return Fraction(rating.maimai_rating(const, score))
    return rating.chunithm_rating(const, int(score))


def fmt_rating(game: str, value: Fraction) -> str:
    return str(int(value)) if game == "maimai" else f"{float(value):.2f}"


def fmt_score(game: str, score: float) -> str:
    return f"{score:.4f}%" if game == "maimai" else f"{int(score):,}"


# ------------------------------------------------------------------ reach


def reach_score(game: str, const: float, target: float) -> float | None:
    """Lowest score/achievement on a chart of `const` that gives at least `target` rating."""
    goal = Fraction(str(target))
    if game == "maimai":
        lo, hi = 0, 1_005_000  # achievement in 1/10000 %
        if chart_rating(game, const, hi / 10000) < goal:
            return None
        while lo < hi:
            mid = (lo + hi) // 2
            if chart_rating(game, const, mid / 10000) >= goal:
                hi = mid
            else:
                lo = mid + 1
        return lo / 10000
    lo, hi = 0, 1_010_000
    if chart_rating(game, const, hi) < goal:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if chart_rating(game, const, mid) >= goal:
            hi = mid
        else:
            lo = mid + 1
    return lo


# ---------------------------------------------------------------- charts


def playable(chart: CatalogChart) -> bool:
    """Charts that count for rating (skips WORLD'S END and anything without a constant)."""
    return chart.level_const > 0


def charts_in_range(db: SongDB, game: str, lo: float, hi: float) -> list[tuple[CatalogSong, CatalogChart]]:
    out = [
        (song, chart)
        for song in db.catalog.get(game, [])
        for chart in song.charts
        if playable(chart) and lo - 1e-9 <= chart.level_const <= hi + 1e-9
    ]
    return sorted(out, key=lambda sc: (-sc[1].level_const, normalize_title(sc[0].title)))


def random_charts(db: SongDB, game: str, lo: float, hi: float, count: int,
                  rng: random.Random | None = None) -> list[tuple[CatalogSong, CatalogChart]]:
    pool = charts_in_range(db, game, lo, hi)
    rng = rng or random.Random()
    return rng.sample(pool, min(count, len(pool)))


def find_chart(song: CatalogSong, difficulty: str) -> CatalogChart | None:
    """Match a difficulty loosely: "MAS", "master", "DX MAS", "Re:MAS"..."""
    want = difficulty.replace(" ", "").replace(":", "").lower()
    for chart in song.charts:
        names = {chart.difficulty, short(chart.difficulty)}
        if any(n.replace(" ", "").replace(":", "").lower() == want for n in names):
            return chart
    return None


def is_new_version(chart: CatalogChart, new_versions: list[str]) -> bool:
    wanted = {v.strip().lower() for v in new_versions}
    return chart.display_version.strip().lower() in wanted


# ---------------------------------------------------------------- what if


@dataclass
class WhatIf:
    before: Fraction
    after: Fraction
    entry: Entry
    counted: bool  # does the new score make it into the B50?


def what_if(b50: B50, song: CatalogSong, chart: CatalogChart, score: float, is_new: bool) -> WhatIf:
    game = b50.game
    entry = make_entry(game, song.title, chart.difficulty, chart.level, chart.level_const, score, None, is_new)
    same = lambda e: normalize_title(e.title) == normalize_title(song.title) and e.difficulty == chart.difficulty  # noqa: E731
    pool = [e for e in b50.old + b50.new if not same(e)]
    existing = [e for e in b50.old + b50.new if same(e)]
    best = max([entry, *existing], key=lambda e: e.rating)
    after = select_b50(game, b50.username, pool + [best])
    counted = best is entry and any(e is entry for e in after.old + after.new)
    return WhatIf(before=b50.total, after=after.total, entry=entry, counted=counted)


# -------------------------------------------------------------- recommend


@dataclass
class Recommendation:
    song: CatalogSong
    chart: CatalogChart
    target_score: float
    gain: Fraction  # rating gained for the B50 total (before averaging for CHUNITHM)


def recommend(db: SongDB, b50: B50, new_versions: list[str], count: int = 5,
              rng: random.Random | None = None) -> list[Recommendation]:
    """Charts outside the B50 where your usual score would push out the weakest entry."""
    game = b50.game
    entries = b50.old + b50.new
    if not entries:
        return []
    usual = statistics.median(e.score for e in entries)
    have = {(normalize_title(e.title), e.difficulty) for e in entries}
    floors = {
        False: min((e.rating for e in b50.old), default=Fraction(0)),
        True: min((e.rating for e in b50.new), default=Fraction(0)),
    }
    candidates = []
    for song in db.catalog.get(game, []):
        for chart in song.charts:
            if not playable(chart) or (normalize_title(song.title), chart.difficulty) in have:
                continue
            new = is_new_version(chart, new_versions)
            gain = chart_rating(game, chart.level_const, usual) - floors[new]
            if gain > 0:
                candidates.append(Recommendation(song, chart, usual, gain))
    # prefer the easiest charts that still help, with a little variety
    candidates.sort(key=lambda r: (r.chart.level_const, -r.gain))
    head = candidates[: max(count * 4, count)]
    rng = rng or random.Random()
    picked = rng.sample(head, min(count, len(head)))
    return sorted(picked, key=lambda r: -r.gain)
