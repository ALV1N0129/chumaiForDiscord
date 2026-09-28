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


# ----------------------------------------------------------------- levels

# where the "+" levels start: CHUNITHM 14+ = 14.5~14.9, maimai 14+ = 14.6~14.9
PLUS_FROM = {"chunithm": 5, "maimai": 6}
LEVEL_HELP = "레벨 (14+), 상수 (14.5), 범위 (14.0-14.8, 13+-14, 15-) 중 하나"


def _level_bounds(text: str, game: str) -> tuple[float, float]:
    t = text.strip()
    if not t:
        raise ValueError("레벨이 비어 있어요.")
    plus = PLUS_FROM[game]
    if t.endswith("+"):
        whole = int(t[:-1])
        return whole + plus / 10, whole + 0.9
    if "." in t:
        v = round(float(t), 1)
        return v, v
    whole = int(t)
    return float(whole), whole + (plus - 1) / 10


def parse_level(text: str, game: str) -> tuple[float, float]:
    """"14" / "14+" / "14.5" / "14.0-14.8" / "13+-14" / "15-" / "-12" -> (min const, max const)."""
    t = text.replace(" ", "").replace("~", "-")
    try:
        if "-" in t:
            lo_s, _, hi_s = t.partition("-")
            lo = _level_bounds(lo_s, game)[0] if lo_s else 1.0
            hi = _level_bounds(hi_s, game)[1] if hi_s else 16.0
        else:
            lo, hi = _level_bounds(t, game)
    except ValueError:
        raise ValueError(f"`{text}` 을(를) 레벨로 읽지 못했어요. {LEVEL_HELP}") from None
    if lo > hi:
        raise ValueError(f"범위가 거꾸로예요: {text}")
    return lo, hi


def describe_level(text: str, lo: float, hi: float) -> str:
    if lo == hi:
        return f"{lo:.1f}"
    if "+" in text or "." not in text:  # a level like 14+ / 13-14: show what it covers
        return f"{text} ({lo:.1f}~{hi:.1f})"
    return f"{lo:.1f}~{hi:.1f}"


DIFF_ORDER = ["BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA", "Basic", "Advanced", "Expert", "Master",
              "Re:Master", "DX Basic", "DX Advanced", "DX Expert", "DX Master", "DX Re:Master"]


def sort_charts(charts: list[CatalogChart]) -> list[CatalogChart]:
    return sorted(charts, key=lambda c: DIFF_ORDER.index(c.difficulty) if c.difficulty in DIFF_ORDER else 99)


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
    song_rating: Fraction | None = None  # rating of the chart at target_score
    replaces: Entry | None = None  # the B50 entry it pushes out
    is_new: bool = False  # goes into the new-version section
    before: Fraction | None = None  # B50 total now
    after: Fraction | None = None  # B50 total with this score


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
                candidates.append(Recommendation(song, chart, usual, gain, is_new=new))
    # biggest gains among charts no harder than what is already in the B50, with a little variety
    ceiling = max(e.level_const for e in entries) + 0.2
    reachable = [r for r in candidates if r.chart.level_const <= ceiling] or candidates
    reachable.sort(key=lambda r: (-r.gain, r.chart.level_const))
    head = reachable[: max(count * 3, count)]
    rng = rng or random.Random()
    picked = rng.sample(head, min(count, len(head)))
    for r in picked:
        section = b50.new if r.is_new else b50.old
        r.replaces = min(section, key=lambda e: e.rating, default=None)
        result = what_if(b50, r.song, r.chart, usual, r.is_new)
        r.song_rating, r.before, r.after = result.entry.rating, result.before, result.after
    return sorted(picked, key=lambda r: (-(r.after - r.before), -r.gain))
