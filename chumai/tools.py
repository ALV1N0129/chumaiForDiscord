"""Game logic behind the utility commands (no Discord code here, so it is easy to test)."""

from __future__ import annotations

import random
from collections.abc import Callable
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
    raw_before: Fraction | None = None  # B50 average (CHUNITHM) / sum (maimai) before truncating
    raw_after: Fraction | None = None
    expected: float | None = None  # maimai: your expected achievement on a chart of this constant
    best: float | None = None  # your best score on it so far, if played
    honey: float | None = None  # maimai: how much easier than its constant it plays (player statistics)


# CHUNITHM: a realistic score for a chart, from how far its constant is below your rating
# ("gap"). Based on the rating roadmap translated on the CHUNITHM gallery
# (gall.dcinside.com/mgallery/board/view/?id=cnt&no=54113, originally home.gamer.com.tw
# artwork 5398406): play charts 1.0~2.0 below your rating aiming for SS~SSS. Lower ratings
# reach a rank at a smaller gap than higher ones, so the two anchor sets are blended.
TARGETS_LOW = [(0.6, 1_000_000), (1.1, 1_005_000), (1.7, 1_007_500), (2.3, 1_009_000)]  # rating <= 14
TARGETS_HIGH = [(1.0, 990_000), (1.3, 1_005_000), (1.8, 1_007_500), (2.3, 1_009_000)]  # rating >= 16.5


def _interp(anchors: list[tuple[float, int]], gap: float) -> float:
    for (g0, s0), (g1, s1) in zip(anchors, anchors[1:]):
        if gap <= g1:
            return s0 + (s1 - s0) * (gap - g0) / (g1 - g0)
    return anchors[-1][1]


def chunithm_target(rating: float, const: float) -> int | None:
    """Score to aim for on a chart of `const` at `rating`, or None if it is still too hard."""
    t = min(1.0, max(0.0, (rating - 14.0) / 2.5))
    gap = rating - const
    if gap < TARGETS_LOW[0][0] * (1 - t) + TARGETS_HIGH[0][0] * t - 1e-9:
        return None
    low = _interp(TARGETS_LOW, max(gap, TARGETS_LOW[0][0]))
    high = _interp(TARGETS_HIGH, max(gap, TARGETS_HIGH[0][0]))
    return int(low * (1 - t) + high * t) // 100 * 100


# what the roadmap suggests at each rating (CHUNITHM)
CHUNITHM_ADVICE = [
    (17.30, "15를 SSS+로 · 점수작"),
    (17.20, "15 SSS 이상 · 채보 연구와 점수작"),
    (17.10, "B30을 15 SSS로 채우기"),
    (17.00, "14+는 마지노선 · 15.0부터 SSS"),
    (16.75, "B30을 14+ SSS 이상으로"),
    (16.50, "14.8~14.9 SSS · 15 SS+"),
    (16.25, "14 상위 · 14+ 중하위를 SSS로"),
    (16.00, "14 비중 늘리기 · 14+ 주력곡 · 15는 S+까지"),
    (15.25, "14 SS+~SSS · 14+ SS~SS+ · 13+ SSS"),
    (14.50, "13 SS+~SSS · 13+ SS · 14 S+~SS+"),
    (13.25, "12 SSS · 12+ SS+ · 13 SS · 14 최하위 도전"),
    (12.00, "11 SSS · 11+ SS+ · 12 SS · MASTER 입문"),
    (0.00, "적정 레벨 찾기 · EXPERT S 이상"),
]


def chunithm_advice(rating: float) -> str:
    return next(text for floor, text in CHUNITHM_ADVICE if rating >= floor)


# maimai: the rating formula jumps at these achievements (rank borders), so they are the targets
MAIMAI_TARGETS = [100.5, 100.0, 99.5, 99.0, 98.0, 97.0]
MAIMAI_RANK_NAMES = {100.5: "SSS+", 100.0: "SSS", 99.5: "SS+", 99.0: "SS", 98.0: "S+", 97.0: "S"}
SKILL_WIDTH = 0.3  # how far (in constant) your other scores still say something about a chart
SKILL_SLOPE = 2.5  # achievement % lost per +1.0 constant, to compare scores on nearby constants
TARGET_STRETCH = 0.35  # a border this much above your expected achievement is still a fair target


class MaimaiSkill:
    """Your expected achievement on a chart of a given constant, from the scores you have.

    Each score is moved to the asked constant (SKILL_SLOPE), and the
    weighted median of those (nearer constants weigh more) is the expectation: a typical play,
    not your best one. Harder charts never expect more than easier ones.
    """

    def __init__(self, points: list[tuple[float, float]]):
        self.points = [(c, min(a, 100.5)) for c, a in points if c and a >= 80]
        # 1.0 ~ 15.0 in 0.1 steps, then made non-increasing by pooling neighbours that break it
        # (weighted by how many scores back each one), so a lucky hard chart or a gap between
        # the levels you play doesn't bend the curve
        blocks: list[list] = []  # [value, weight, constants]
        for step in range(10, 151):
            found = self._median(step / 10)
            if found is None:
                continue
            blocks.append([found[0], found[1], [step / 10]])
            while len(blocks) > 1 and blocks[-2][0] < blocks[-1][0]:
                (v2, w2, c2), (v1, w1, c1) = blocks.pop(), blocks.pop()
                blocks.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, c1 + c2])
        self.curve = {c: v for v, _, cs in blocks for c in cs}

    def _median(self, const: float) -> tuple[float, float] | None:
        """(weighted median of your scores moved to `const`, total weight) or None if too few."""
        weighted = []
        for c, a in self.points:
            d = (const - c) / SKILL_WIDTH
            if abs(d) <= 3:
                weighted.append((a - SKILL_SLOPE * (const - c), 2.0 ** (-d * d)))
        total = sum(w for _, w in weighted)
        if total < 1.5:  # too few scores near this constant to say
            return None
        weighted.sort()
        run = 0.0
        for value, w in weighted:
            run += w
            if run >= total / 2:
                return min(100.5, value), total
        return None

    def expected(self, const: float) -> float | None:
        return self.curve.get(round(const, 1))

    def reach(self) -> dict[float, float]:
        """The hardest constant where each rank border is still expected."""
        out = {}
        for t in MAIMAI_TARGETS:
            ok = [c for c, e in self.curve.items() if e >= t - 1e-9]
            if ok:
                out[t] = max(ok)
        return out


Honey = Callable[[str, str], "float | None"]  # (title, difficulty) -> how much easier than its constant


def real_const(const: float, title: str, difficulty: str, honey: Honey | None) -> float:
    """The constant a chart really plays like (its own constant without statistics)."""
    h = honey(title, difficulty) if honey else None
    return const - h if h else const


def maimai_skill(b50: B50, db: SongDB | None = None, honey: Honey | None = None) -> MaimaiSkill:
    """Skill from every played chart when the B50 came with them, else from the B50 itself,
    placed at how hard each chart really plays."""
    points = []
    if b50.played and db is not None:
        for (title, difficulty), score in b50.played.items():
            info = db.maimai_chart(title, difficulty)
            if info is not None and info.level_const:
                points.append((real_const(info.level_const, title, difficulty, honey), score))
    if len(points) < 10:
        points = [(real_const(e.level_const, e.title, e.difficulty, honey), e.score) for e in b50.old + b50.new]
    return MaimaiSkill(points)


def maimai_target(expected: float | None, best: float | None = None) -> float | None:
    """The rank border to aim for: the highest one within a small stretch of your expected
    achievement, if it beats your current best on the chart. None if the chart is still too
    hard (S not expected) or there is nothing to gain."""
    if expected is None or expected < 97.0 - TARGET_STRETCH:
        return None
    t = next(t for t in MAIMAI_TARGETS if t <= expected + TARGET_STRETCH + 1e-9)
    return t if best is None or t > best + 1e-9 else None


def maimai_reach_text(reach: dict[float, float]) -> str:
    return " · ".join(f"{MAIMAI_RANK_NAMES[t]} ~{reach[t]:.1f}" for t in (100.5, 100.0, 99.5, 99.0) if t in reach)


def recommend(db: SongDB, b50: B50, new_versions: list[str], count: int = 5,
              rng: random.Random | None = None, honey: Honey | None = None) -> list[Recommendation]:
    """Charts outside the B50 where a realistic score would push out the weakest entry.

    CHUNITHM: the target score comes from chunithm_target (how far the chart is below your
    rating). maimai: the rank border just around your expected achievement on that constant
    (MaimaiSkill); charts you've played count too if your best there is below that border.
    With `honey` (player statistics), a chart counts as the constant it really plays like, so
    charts that play easier than their number ("꿀곡") get higher targets and come first.
    """
    game = b50.game
    entries = b50.old + b50.new
    if not entries:
        return []
    current = float(b50.total)
    have = {(normalize_title(e.title), e.difficulty) for e in entries}
    floors = {
        False: min((e.rating for e in b50.old), default=Fraction(0)),
        True: min((e.rating for e in b50.new), default=Fraction(0)),
    }
    skill = maimai_skill(b50, db, honey) if game == "maimai" else None
    played = {(normalize_title(t), d): score for (t, d), score in b50.played.items()}
    expect: dict[float, float | None] = {}
    candidates = []
    for song in db.catalog.get(game, []):
        for chart in song.charts:
            key = (normalize_title(song.title), chart.difficulty)
            if not playable(chart) or key in have:
                continue
            best = played.get(key)
            sweet = None
            if game == "chunithm":
                target, expected = chunithm_target(current, chart.level_const), None
            else:
                sweet = honey(song.title, chart.difficulty) if honey else None
                real = round(chart.level_const - (sweet or 0), 1)
                if real not in expect:
                    expect[real] = skill.expected(real)
                expected = expect[real]
                target = maimai_target(expected, best)
            if target is None:
                continue
            new = is_new_version(chart, new_versions)
            gain = chart_rating(game, chart.level_const, target) - floors[new]
            if gain > 0:
                candidates.append(Recommendation(song, chart, target, gain, is_new=new,
                                                 expected=expected, best=best, honey=sweet))
    # spread over difficulties: a random chart from each of the constants that gain the most,
    # then fill up from those constants if there are fewer of them than `count`
    rng = rng or random.Random()
    by_const: dict[float, list[Recommendation]] = {}
    for r in candidates:
        by_const.setdefault(r.chart.level_const, []).append(r)
    sweetness = lambda r: r.honey or 0.0  # noqa: E731
    for group in by_const.values():
        # the most to gain, and of those the sweetest; random among near-equals for variety
        group.sort(key=lambda r: (-r.gain, -sweetness(r)))
        top = [r for r in group if r.gain == group[0].gain and sweetness(r) >= sweetness(group[0]) - 0.1]
        rng.shuffle(top)
        group[: len(top)] = top
    ranked = sorted(by_const.values(), key=lambda g: (-g[0].gain, -sweetness(g[0]), g[0].chart.level_const))
    picked, songs = [], set()

    def take(r: Recommendation) -> None:
        # one chart per song (not its STD and DX charts, or EXPERT and MASTER, side by side)
        if len(picked) < count and normalize_title(r.song.title) not in songs:
            picked.append(r)
            songs.add(normalize_title(r.song.title))

    for g in ranked[:count]:  # a random chart from each of the best constants
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
    return sorted(picked, key=lambda r: (-(r.raw_after - r.raw_before), -r.gain))
