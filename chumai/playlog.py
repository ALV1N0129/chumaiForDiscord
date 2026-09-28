"""Turn play-log records into entries (with constants and jackets) and credit images."""

from __future__ import annotations

from dataclasses import dataclass

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


def _same(a: float, b: float) -> bool:
    return abs(a - b) < 5e-5  # maimai achievements have 4 decimals


def badges(plays: list[PlayRecord], cache: dict[tuple[str, str], float], cache_key: str | None,
           now: dict[tuple[str, str], float]) -> dict[str, Badge]:
    """Badge for each play (by play key).

    cache: best scores as of the play `cache_key` (so plays after it are not in it yet).
    now: best scores right now, from the record pages (used when the cache can't tell).
    """
    running = dict(cache)
    out: dict[str, Badge] = {}
    for r in sorted(plays, key=lambda r: r.key):
        k = (r.title, r.difficulty)
        known = cache_key is not None and r.key > cache_key
        prev = running.get(k) if known else None
        if r.new_record:
            out[r.key] = Badge("new", delta=r.score - prev if prev is not None else None)
            if known:
                running[k] = r.score
            continue
        best = prev if prev is not None else now.get(k, cache.get(k))
        if best is None:
            continue
        out[r.key] = Badge("tie") if _same(r.score, best) else Badge("best", best=best)
    return out


__all__ = ["to_entry", "level_to_min_const", "Badge", "badges"]
