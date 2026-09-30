"""Turn play-log records into entries (with constants and jackets) and credit images."""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

from .b50 import UNRATED, Entry, make_entry
from .net_parsers import PlayRecord
from .songdb import SongDB, level_to_min_const


def to_entry(game: str, r: PlayRecord, songdb: SongDB, levels=None) -> Entry:
    """levels(title, difficulty): official level of an unrated (WORLD'S END / 宴) chart, if known."""
    if r.difficulty in UNRATED:
        level = (levels(r.title, r.difficulty) if levels else None) or "?"
        e = make_entry(game, r.title, r.difficulty, level, 0.0, r.score, r.lamp, False)
        return _with_rank(e, r) if game == "maimai" else e
    if game == "chunithm":
        info = songdb.chunithm_chart_by_title(r.title, r.difficulty)
    else:
        info = songdb.maimai_chart(r.title, r.difficulty, r.genre)
    level = info.level if info else "?"
    const = info.level_const if info else 0.0
    if not info and game == "maimai":
        const = 0.0
    e = make_entry(game, r.title, r.difficulty, level, const, r.score, r.lamp, False)
    return _with_rank(e, r) if game == "maimai" else e


def _with_rank(e: Entry, r: PlayRecord) -> Entry:
    if r.rank:  # maimai: the site's rank (the achievement alone can't tell every border)
        e.rank = r.rank
    return e


@dataclass
class Badge:
    """What to show next to a play: "new" (with the improvement if known), "tie" or "best"."""

    kind: str
    delta: float | None = None
    best: float | None = None
    gain: Fraction | None = None  # how much this play raised the player rating (unrounded), if it did
    first: bool = False  # a new record on a chart never played before (the saved bests say so)


def _same(a: float, b: float) -> bool:
    return abs(a - b) < 5e-5  # maimai achievements have 4 decimals


def b50_sum(game: str, songdb: SongDB, new_versions: list[str], bests: dict[tuple[str, str], float]) -> Fraction:
    """Player rating (unrounded: CHUNITHM average, maimai sum) from best scores."""
    from . import tools
    from .b50 import SLOTS

    sections: dict[bool, list[Fraction]] = {False: [], True: []}
    for (title, difficulty), score in bests.items():
        if game == "chunithm":
            info = songdb.chunithm_chart_by_title(title, difficulty)
        else:
            info = songdb.maimai_chart(title, difficulty)
        if info is None or not info.level_const:
            continue
        new = tools.is_new_version(info, new_versions)
        sections[new].append(tools.chart_rating(game, info.level_const, score))
    old_slots, new_slots = SLOTS[game]
    total = sum(sorted(sections[False], reverse=True)[:old_slots], Fraction(0)) + \
        sum(sorted(sections[True], reverse=True)[:new_slots], Fraction(0))
    return total / 50 if game == "chunithm" else total


def badges(plays: list[PlayRecord], cache: dict[tuple[str, str], float], cache_key: str | None,
           now: dict[tuple[str, str], float], songdb: SongDB | None = None,
           new_versions: list[str] | None = None, game: str | None = None) -> dict[str, Badge]:
    """Badge for each play (by play key).

    cache: best scores as of the play `cache_key` (so plays after it are not in it yet).
    now: best scores right now, from the record pages (used when the cache can't tell).
    With songdb/new_versions/game, new records also get how much they raised the player rating.
    """
    running = dict(cache)
    rate = songdb is not None and new_versions is not None and game is not None and bool(cache)
    # difficulties the saved bests cover (WORLD'S END / 宴 only since they're saved too): a chart
    # missing there was never played
    covered = {d for _, d in cache}
    total = b50_sum(game, songdb, new_versions, running) if rate else None
    out: dict[str, Badge] = {}
    for r in sorted(plays, key=lambda r: r.key):
        k = (r.title, r.difficulty)
        known = cache_key is not None and r.key > cache_key
        prev = running.get(k) if known else None
        if r.new_record:
            badge = Badge("new", delta=r.score - prev if prev is not None else None,
                          first=known and prev is None and (r.difficulty in covered or r.difficulty not in UNRATED))
            if known:
                running[k] = r.score
                if rate:
                    after = b50_sum(game, songdb, new_versions, running)
                    if after > total:
                        badge.gain = after - total
                    total = after
            out[r.key] = badge
            continue
        best = prev if prev is not None else now.get(k, cache.get(k))
        if best is None:
            continue
        out[r.key] = Badge("tie") if _same(r.score, best) else Badge("best", best=best)
    return out


LAMP_ORDER = ["AP+", "AJC", "AP", "AJ", "FC+", "FC"]  # best first


@dataclass
class DaySlotData:
    """Plays of one chart in a row within a credit (/today)."""

    play: PlayRecord  # the best of them, with the best lamp of them
    new: bool  # any a new record
    count: int
    gain: float  # how much they raised the player rating
    delta: float | None  # how much they beat the best from before, if known
    first: bool  # never played before


def day_timeline(plays: list[PlayRecord], marks: dict[str, Badge]):
    """A day's plays for /today's timeline: ([(credit's time, [DaySlotData])], [(credit, where in it
    0..1, rating gained, slot)]). Plays of one chart in a row within a credit are one slot."""
    from .net_parsers import group_credits

    credits, steps = [], []
    for ci, credit in enumerate(group_credits(sorted(plays, key=lambda r: r.key))):
        slots: list[list[PlayRecord]] = []
        for ti, r in enumerate(credit):
            if slots and (slots[-1][-1].title, slots[-1][-1].difficulty) == (r.title, r.difficulty):
                slots[-1].append(r)
            else:
                slots.append([r])
            gain = getattr(marks.get(r.key), "gain", None)
            if gain:
                steps.append((ci, (ti + 0.5) / len(credit), float(gain), len(slots) - 1))
        out = []
        for si, group in enumerate(slots):
            top = max(group, key=lambda r: (r.score, r.key))
            lamps = [r.lamp for r in group if r.lamp in LAMP_ORDER]
            if lamps:
                top = replace(top, lamp=min(lamps, key=LAMP_ORDER.index))
            gained = sum(g for c, _, g, slot in steps if c == ci and slot == si)
            fresh = [marks[r.key] for r in group if r.new_record and r.key in marks]
            first = any(b.first for b in fresh)
            deltas = [b.delta for b in fresh]
            delta = sum(deltas) if deltas and None not in deltas and not first else None
            out.append(DaySlotData(top, any(r.new_record for r in group), len(group), gained, delta, first))
        credits.append((credit[0].date[-5:], out))
    return credits, steps


__all__ = ["to_entry", "level_to_min_const", "Badge", "badges", "day_timeline", "DaySlotData"]
