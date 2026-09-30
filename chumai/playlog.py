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
    total = b50_sum(game, songdb, new_versions, running) if rate else None
    out: dict[str, Badge] = {}
    for r in sorted(plays, key=lambda r: r.key):
        k = (r.title, r.difficulty)
        known = cache_key is not None and r.key > cache_key
        prev = running.get(k) if known else None
        if r.new_record:
            badge = Badge("new", delta=r.score - prev if prev is not None else None)
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


def by_chart(plays: list[PlayRecord], marks: dict[str, Badge]) -> list[tuple[PlayRecord, Badge | None, int]]:
    """A day's plays, one row per chart (/today): (the best play, with the day's best lamp; the
    day's badge; how many times it was played). The day's badge: NEW when any play set a new
    record, by how much over the best before the day and with the rating gained, else the best
    play's TIE / BEST. Charts with a new record first, the biggest gains on top, then the rest,
    the latest played first."""
    charts: dict[tuple[str, str], list[PlayRecord]] = {}
    for r in sorted(plays, key=lambda r: r.key):
        charts.setdefault((r.title, r.difficulty), []).append(r)
    rows = []
    for group in charts.values():
        top = max(group, key=lambda r: (r.score, r.key))
        lamps = [r.lamp for r in group if r.lamp in LAMP_ORDER]
        if lamps:
            top = replace(top, lamp=min(lamps, key=LAMP_ORDER.index))
        new = [marks[r.key] for r in group if r.new_record and r.key in marks]
        if new:
            deltas = [b.delta for b in new]
            badge = Badge("new", delta=None if None in deltas else sum(deltas),
                          gain=sum((b.gain for b in new if b.gain), Fraction(0)) or None)
        elif any(r.new_record for r in group):
            badge = Badge("new")
        else:
            badge = marks.get(top.key)
        rows.append((top, badge, len(group), group[-1].key))
    fresh = sorted((row for row in rows if row[1] is not None and row[1].kind == "new"),
                   key=lambda row: (float(row[1].gain or 0), row[1].delta or 0), reverse=True)
    rest = sorted((row for row in rows if row[1] is None or row[1].kind != "new"), key=lambda row: row[3], reverse=True)
    return [row[:3] for row in fresh + rest]


__all__ = ["to_entry", "level_to_min_const", "Badge", "badges", "by_chart"]
