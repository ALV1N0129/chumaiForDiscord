"""Game logic behind the utility commands (no Discord code here, so it is easy to test)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from fractions import Fraction

from . import rating
from .b50 import SLOTS, B50, Entry, make_entry, select_b50
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


def reach_score(game: str, const: float, target: float | Fraction) -> float | None:
    """Lowest score/achievement on a chart of `const` that gives at least `target` rating."""
    goal = target if isinstance(target, Fraction) else Fraction(str(target))
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


# song categories (genres) by the words people use for them: a word -> parts of genre names to look
# for, in order (the two games name theirs differently)
_ORIGINAL, _VARIETY, _CROSS = ["original", "maimai"], ["variety", "ゲーム"], ["ゲキマイ", "オンゲキ"]
CATEGORY_WORDS = {
    "오리지널": _ORIGINAL, "오리": _ORIGINAL, "original": _ORIGINAL, "마이마이": ["maimai"], "maimai": ["maimai"],
    "팝스": ["pops"], "애니": ["pops"], "팝": ["pops"], "pops": ["pops"], "anime": ["pops"],
    "니코": ["niconico"], "니코니코": ["niconico"], "보카로": ["niconico"], "niconico": ["niconico"],
    "vocaloid": ["niconico"],
    "버라이어티": _VARIETY, "variety": _VARIETY, "게임": _VARIETY, "game": _VARIETY,
    "게키마이": _CROSS, "gekimai": _CROSS, "온게키": _CROSS, "ongeki": _CROSS, "츄니즘": _CROSS, "chunithm": _CROSS,
    "동방": ["東方"], "touhou": ["東方"], "이로도리": ["イロドリ"], "이로드리": ["イロドリ"], "irodorimidori": ["イロドリ"],
}
CATEGORY_HELP = "카테고리: 오리지널, 팝스, 니코, 버라이어티, 동방, 게키마이(온게키), 이로도리"


def genres(db: SongDB, game: str) -> list[str]:
    return sorted({s.genre for s in db.catalog.get(game, []) if s.genre})


def parse_category(text: str, db: SongDB, game: str) -> str | None:
    """The genre `text` names (오리지널, 동방, POPS & ANIME…), or None."""
    word = normalize_title(text).replace(" ", "")
    names = {g: normalize_title(g).replace(" ", "") for g in genres(db, game)}
    for key in CATEGORY_WORDS.get(word, [word]):
        found = [g for g, name in names.items() if key in name]
        if len(found) == 1:
            return found[0]
    return None


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


def _diff_key(name: str) -> str:
    return name.replace(" ", "").replace(":", "").lower()


def find_chart_name(difficulty: str) -> str | None:
    """The full difficulty name for "MAS", "master", "DX MAS", "Re:MAS"... or None."""
    want = _diff_key(difficulty)
    return next((d for d in DIFF_ORDER if want in (_diff_key(d), _diff_key(short(d)))), None)


def find_chart(song: CatalogSong, difficulty: str) -> CatalogChart | None:
    """Match a difficulty loosely: "MAS", "master", "DX MAS", "Re:MAS"..."""
    want = _diff_key(difficulty)
    for chart in song.charts:
        names = {chart.difficulty, short(chart.difficulty)}
        if any(_diff_key(n) == want for n in names):
            return chart
    return None


def in_region(b50: B50, song: CatalogSong, chart: CatalogChart) -> bool:
    """False for a chart the player's record pages don't list, e.g. not out yet on the international
    version (b50.available: music ids for CHUNITHM, normalized titles for maimai). True when that
    difficulty wasn't checked."""
    if not b50.available or chart.difficulty not in b50.available:
        return True
    have = b50.available[chart.difficulty]
    if b50.game == "chunithm":
        return song.music_id in have
    return normalize_title(song.title) in have


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


def all_done(b50: B50, recs: list["Recommendation"]) -> B50:
    """The B50 after getting the target on every recommended chart (each pushing out whatever is
    weakest by then)."""
    game = b50.game
    extra = [make_entry(game, r.song.title, r.chart.difficulty, r.chart.level, r.chart.level_const,
                        r.target_score, None, r.is_new) for r in recs]
    return select_b50(game, b50.username, b50.old + b50.new + extra)


def all_done_steps(b50: B50, recs: list["Recommendation"]) -> list[Fraction]:
    """Unrounded rating (CHUNITHM average, maimai sum) now and after each of `recs` in turn."""
    div = 50 if b50.game == "chunithm" else 1
    raw = lambda b: (b.old_sum + b.new_sum) / div  # noqa: E731
    return [raw(b50)] + [raw(all_done(b50, recs[: i + 1])) for i in range(len(recs))]


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
    raw_before: Fraction | None = None  # B50 average (CHUNITHM) / sum (maimai) before truncating
    raw_after: Fraction | None = None
    entry: float | None = None  # the lowest rank at which it counts
    cut: float | None = None  # the exact lowest score at which it counts
    best: float | None = None  # your best score on it so far, if played


# The rating formulas jump at these scores (rank borders), so they are the targets.
RANK_TARGETS = {
    "maimai": [100.5, 100.0, 99.5, 99.0, 98.0, 97.0],  # SSS+ SSS SS+ SS S+ S
    "chunithm": [1_009_000, 1_007_500, 1_005_000, 1_000_000, 990_000, 975_000],
}
BAND = 0.25  # the scores that say what you get on a constant: charts this close to it, either way
MIN_BAND_SCORES = 3


def played_scores(b50: B50, db: SongDB | None = None) -> tuple[list[tuple[float, float]], bool]:
    """(constant, score) of every played chart when the B50 came with them (True), else of the
    B50 (False)."""
    points = []
    if b50.played and db is not None:
        for (title, difficulty), score in b50.played.items():
            if b50.game == "maimai":
                info = db.maimai_chart(title, difficulty)
            else:
                info = db.chunithm_chart_by_title(title, difficulty)
            if info is not None and info.level_const:
                points.append((info.level_const, score))
    if len(points) >= len(b50.old + b50.new):
        return points, True
    return [(e.level_const, e.score) for e in b50.old + b50.new], False


# Where in your scores around a constant "the rank you usually get" sits. The B50 is already your
# best charts, so its middle. All played charts include old scores from charts you tried once and
# never went back to, so the upper quarter there (a rank you have on at least 1 in 4 of them).
USUAL_B50, USUAL_PLAYED = 0.5, 0.75


def usual_rank(game: str, points: list[tuple[float, float]], const: float, usual: float = USUAL_B50) -> float | None:
    """The rank you usually get around `const`: the border under the `usual` quantile of your
    scores on charts within BAND of `const` (None with fewer than MIN_BAND_SCORES there)."""
    band = sorted(a for c, a in points if abs(c - const) <= BAND + 1e-9)
    if len(band) < MIN_BAND_SCORES:
        return None
    typical = band[int((len(band) - 1) * usual)]  # rounded down: a typical play, not a good day
    return next((t for t in RANK_TARGETS[game] if typical >= t), None)


def entry_rank(game: str, const: float, floor: Fraction) -> float | None:
    """The lowest rank border at which a chart of `const` beats `floor` (None: not even the top)."""
    return next((t for t in reversed(RANK_TARGETS[game]) if chart_rating(game, const, t) > floor), None)


def entry_score(game: str, const: float, floor: Fraction) -> float | None:
    """The exact lowest score on a chart of `const` whose rating beats `floor` (the B50 cut)."""
    step = Fraction(1) if game == "maimai" else Fraction(1, 100)  # maimai ratings are whole, CHUNITHM's 0.01
    return reach_score(game, const, floor + step)


def pick_target(usual: float | None, entry: float | None, best: float | None = None) -> float | None:
    """Aim for the rank you usually get on charts this hard, if that is enough to count and beats your best."""
    if usual is None or entry is None or usual < entry:
        return None
    return usual if best is None or usual > best + 1e-9 else None


def recommend(db: SongDB, b50: B50, new_versions: list[str], count: int = 5,
              rng: random.Random | None = None) -> list[Recommendation]:
    """Charts outside the B50 that the rank you usually get on charts that hard would put in it,
    easiest (lowest constant) first. Only the rating formula and your own scores: the target is
    usual_rank, and entry_rank is the least that still pushes out the weakest entry.
    """
    game = b50.game
    entries = b50.old + b50.new
    if not entries:
        return []
    have = {(normalize_title(e.title), e.difficulty) for e in entries}
    floors = {
        False: min((e.rating for e in b50.old), default=Fraction(0)),
        True: min((e.rating for e in b50.new), default=Fraction(0)),
    }
    points, all_played = played_scores(b50, db)
    usual = USUAL_PLAYED if all_played else USUAL_B50
    played = {(normalize_title(t), d): score for (t, d), score in b50.played.items()}
    proven: dict[float, float | None] = {}
    candidates = []
    for song in db.catalog.get(game, []):
        for chart in song.charts:
            key = (normalize_title(song.title), chart.difficulty)
            if not playable(chart) or key in have or not in_region(b50, song, chart):
                continue
            best = played.get(key)
            new = is_new_version(chart, new_versions)
            if chart.level_const not in proven:
                proven[chart.level_const] = usual_rank(game, points, chart.level_const, usual)
            entry = entry_rank(game, chart.level_const, floors[new])
            target = pick_target(proven[chart.level_const], entry, best)
            if target is None:
                continue
            gain = chart_rating(game, chart.level_const, target) - floors[new]
            if gain > 0:
                candidates.append(Recommendation(song, chart, target, gain, is_new=new, entry=entry, best=best,
                                                 cut=entry_score(game, chart.level_const, floors[new])))
    # spread over difficulties: a random chart from each of the easiest constants that count,
    # then fill up from those constants if there are fewer of them than `count`
    rng = rng or random.Random()
    by_const: dict[float, list[Recommendation]] = {}
    for r in candidates:
        by_const.setdefault(r.chart.level_const, []).append(r)
    for group in by_const.values():
        group.sort(key=lambda r: -r.gain)
        top = [r for r in group if r.gain == group[0].gain]  # random among equals for variety
        rng.shuffle(top)
        group[: len(top)] = top
    # the easiest charts that still count come first
    ranked = sorted(by_const.values(), key=lambda g: (g[0].chart.level_const, -g[0].gain))
    picked, songs = [], set()

    def take(r: Recommendation) -> None:
        # one chart per song (not its STD and DX charts, or EXPERT and MASTER, side by side)
        if len(picked) < count and normalize_title(r.song.title) not in songs:
            picked.append(r)
            songs.add(normalize_title(r.song.title))

    for g in ranked[:count]:  # a random chart from each of the easiest constants
        r = next((r for r in g if normalize_title(r.song.title) not in songs), None)
        if r is not None:
            take(r)
    rest = [r for g in ranked[:count] for r in g]
    rng.shuffle(rest)
    for r in rest + [r for g in ranked[count:] for r in g]:
        take(r)
    for r in picked:
        section = b50.new if r.is_new else b50.old
        r.replaces = min(section, key=lambda e: e.rating, default=None)
        result = what_if(b50, r.song, r.chart, r.target_score, r.is_new)
        r.song_rating, r.before, r.after = result.entry.rating, result.before, result.after
        slots = SLOTS[game][1 if r.is_new else 0]
        pushed_out = r.replaces.rating if r.replaces is not None and len(section) >= slots else Fraction(0)
        divisor = 50 if game == "chunithm" else 1
        r.raw_before = (b50.old_sum + b50.new_sum) / divisor
        r.raw_after = r.raw_before + (r.song_rating - pushed_out) / divisor
    return sorted(picked, key=lambda r: (r.chart.level_const, -r.gain))
