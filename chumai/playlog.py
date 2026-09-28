"""Turn play-log records into entries (with constants and jackets) and credit images."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .b50 import Entry, make_entry
from .net_parsers import PlayRecord
from .songdb import SongDB, level_to_min_const


def to_entry(game: str, r: PlayRecord, songdb: SongDB) -> Entry:
    if game == "chunithm":
        info = songdb.chunithm_chart_by_title(r.title, r.difficulty)
    else:
        info = songdb.maimai_chart(r.title, r.difficulty, r.genre)
    level = info.level if info else "?"
    const = info.level_const if info else 0.0
    if not info and game == "maimai":
        const = 0.0
    e = make_entry(game, r.title, r.difficulty, level, const, r.score, r.lamp, False)
    if game == "maimai" and r.rank:
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


__all__ = ["to_entry", "level_to_min_const", "Badge", "badges"]
