"""Chart constants and versions, taken from Tachi's public seed data on GitHub.

CHUNITHM-NET and maimai DX NET show scores but not chart constants, so we look
those up here. The seeds are downloaded from GitHub and cached on disk.
"""

from __future__ import annotations

import json
import logging
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import aiohttp

log = logging.getLogger(__name__)

SEEDS_URL = "https://raw.githubusercontent.com/TNG-dev/Tachi/main/db/seeds"
REFRESH_SECONDS = 24 * 60 * 60

# maimai DX NET (international) genre names -> Tachi genre names
MAIMAI_GENRES = {
    "POPS&ANIME": "POPS＆アニメ",
    "NICONICO&VOCALOID": "niconico＆ボーカロイド",
    "TOUHOUPROJECT": "東方Project",
    "東方PROJECT": "東方Project",
    "GAME&VARIETY": "ゲーム＆バラエティ",
    "MAIMAI": "maimai",
    "ONGEKI&CHUNITHM": "オンゲキ＆CHUNITHM",
}


@dataclass(frozen=True)
class ChartInfo:
    title: str
    genre: str
    level: str
    level_const: float
    display_version: str


@dataclass
class CatalogChart:
    difficulty: str
    level: str
    level_const: float
    display_version: str


@dataclass
class CatalogSong:
    game: str  # "chunithm" / "maimai"
    title: str
    artist: str
    genre: str
    keys: list[str]  # normalized title + alternative titles / search terms
    charts: list[CatalogChart]
    music_id: int | None = None  # CHUNITHM in-game id (for jackets)

    @property
    def jacket_key(self):
        return self.music_id if self.game == "chunithm" else (self.title, self.genre)


def normalize_title(title: str) -> str:
    return unicodedata.normalize("NFKC", title).strip().lower()


def normalize_genre(genre: str) -> str:
    g = unicodedata.normalize("NFKC", genre).replace(" ", "").upper()
    return unicodedata.normalize("NFKC", MAIMAI_GENRES.get(g, genre))


def level_to_min_const(level: str, game: str) -> float:
    """Fallback constant when a chart isn't in the database (e.g. brand new songs)."""
    try:
        if level.endswith("+"):
            return float(level[:-1]) + (0.6 if game == "maimai" else 0.5)
        return float(level.rstrip("?"))
    except ValueError:
        return 0.0


class SongDB:
    def __init__(self) -> None:
        # CHUNITHM: (in-game id, difficulty) -> chart
        self.chunithm: dict[tuple[int, str], ChartInfo] = {}
        # maimai: (normalized title, "DX Master"/"Master"/...) -> charts (several if titles collide)
        self.maimai: dict[tuple[str, str], list[ChartInfo]] = {}
        # CHUNITHM by (normalized title, difficulty), for play logs that have no music id
        self.chunithm_titles: dict[tuple[str, str], ChartInfo] = {}
        # every song with all of its charts, for search / random / const lists
        self.catalog: dict[str, list[CatalogSong]] = {"chunithm": [], "maimai": []}

    def load(self, seeds: dict[str, list[dict]]) -> None:
        for game in ("chunithm", "maimaidx"):
            songs = {s["id"]: s for s in seeds[f"songs-{game}"]}
            name = "maimai" if game == "maimaidx" else "chunithm"
            by_song: dict[str, CatalogSong] = {}
            for sid, song in songs.items():
                keys = [normalize_title(t) for t in [song["title"], *song.get("altTitles", []),
                                                     *song.get("searchTerms", [])] if t]
                by_song[sid] = CatalogSong(name, song["title"], song.get("artist", ""),
                                           song.get("data", {}).get("genre", ""), keys, [])
            for c in seeds[f"charts-{game}"]:
                cs = by_song.get(c["songID"])
                if cs is None:
                    continue
                cs.charts.append(CatalogChart(c["difficulty"], str(c["level"]), float(c["levelNum"]),
                                              c.get("data", {}).get("displayVersion", "")))
                ids = c.get("data", {}).get("inGameID")
                if name == "chunithm" and cs.music_id is None and ids is not None:
                    cs.music_id = int(ids[0] if isinstance(ids, list) else ids)
            self.catalog[name] = [cs for cs in by_song.values() if cs.charts]
            for c in seeds[f"charts-{game}"]:
                song = songs.get(c["songID"])
                if song is None:
                    continue
                info = ChartInfo(
                    title=song["title"],
                    genre=song.get("data", {}).get("genre", ""),
                    level=str(c["level"]),
                    level_const=float(c["levelNum"]),
                    display_version=c.get("data", {}).get("displayVersion", ""),
                )
                if game == "chunithm":
                    ids = c["data"].get("inGameID")
                    for i in ids if isinstance(ids, list) else [ids]:
                        if i is not None:
                            self.chunithm[(int(i), c["difficulty"])] = info
                    self.chunithm_titles.setdefault((normalize_title(song["title"]), c["difficulty"]), info)
                else:
                    for t in [song["title"], *song.get("altTitles", [])]:
                        self.maimai.setdefault((normalize_title(t), c["difficulty"]), []).append(info)

    def chunithm_chart(self, idx: int, difficulty: str) -> ChartInfo | None:
        return self.chunithm.get((idx, difficulty))

    def chunithm_chart_by_title(self, title: str, difficulty: str) -> ChartInfo | None:
        return self.chunithm_titles.get((normalize_title(title), difficulty))

    def maimai_chart(self, title: str, difficulty: str, genre: str | None = None) -> ChartInfo | None:
        found = self.maimai.get((normalize_title(title), difficulty))
        if not found:
            return None
        if len(found) > 1 and genre:
            g = normalize_genre(genre)
            for info in found:
                if unicodedata.normalize("NFKC", info.genre) == g:
                    return info
        return found[0]

    async def load_or_update(self, cache_dir: str | Path, base_url: str = SEEDS_URL) -> None:
        cache = Path(cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        names = ["songs-chunithm", "charts-chunithm", "songs-maimaidx", "charts-maimaidx"]
        stale = any(
            not (cache / f"{n}.json").exists()
            or time.time() - (cache / f"{n}.json").stat().st_mtime > REFRESH_SECONDS
            for n in names
        )
        if stale:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
                    for n in names:
                        async with s.get(f"{base_url}/{n}.json") as resp:
                            resp.raise_for_status()
                            data = await resp.read()
                        json.loads(data)  # validate before overwriting the cache
                        (cache / f"{n}.json").write_bytes(data)
                log.info("song database updated")
            except Exception:
                log.exception("failed to download song database; using cached copy if any")

        seeds = {}
        for n in names:
            path = cache / f"{n}.json"
            if not path.exists():
                log.warning("song database is unavailable; chart constants will be estimated")
                return
            seeds[n] = json.loads(path.read_text(encoding="utf-8"))
        self.chunithm.clear()
        self.chunithm_titles.clear()
        self.catalog = {"chunithm": [], "maimai": []}
        self.maimai.clear()
        self.load(seeds)
        log.info("song database loaded: %d CHUNITHM charts, %d maimai charts",
                 len(self.chunithm), sum(len(v) for v in self.maimai.values()))


def search(db: SongDB, game: str, query: str, limit: int = 10) -> list[CatalogSong]:
    """Exact title, then prefix, then substring, then fuzzy matches."""
    import difflib

    q = normalize_title(query)
    if not q:
        return []
    songs = db.catalog.get(game, [])
    exact = [s for s in songs if q in s.keys]
    prefix = [s for s in songs if s not in exact and any(k.startswith(q) for k in s.keys)]
    sub = [s for s in songs if s not in exact and s not in prefix and any(q in k for k in s.keys)]
    found = exact + prefix + sub
    if len(found) < limit:
        key_to_song = {}
        for s in songs:
            for k in s.keys:
                key_to_song.setdefault(k, s)
        for k in difflib.get_close_matches(q, list(key_to_song), n=limit, cutoff=0.6):
            if key_to_song[k] not in found:
                found.append(key_to_song[k])
    return found[:limit]
