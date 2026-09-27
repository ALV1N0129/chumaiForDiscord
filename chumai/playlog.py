"""Turn play-log records into entries (with constants and jackets) and credit images."""

from __future__ import annotations

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


__all__ = ["to_entry", "level_to_min_const"]
