"""Chart constants and versions, taken from Tachi's public seed data on GitHub.

CHUNITHM-NET and maimai DX NET show scores but not chart constants, so we look
those up here. The seeds are downloaded from GitHub and cached on disk.
"""

from __future__ import annotations

import gc
import json
import logging
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import aiohttp

from .jsonstream import download_to, iter_items

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


def _chart_versions(game: str, charts: list[dict]):
    """version(chart) -> the version the chart counts as for NEW / BEST.

    CHUNITHM decides by song: an ULTIMA added to an old song in the current version is still an old
    chart (and counts in BEST 30), so every CHUNITHM chart takes its song's version (the MASTER's).
    maimai keeps each chart's own version (a DX chart added to an old song is new).
    """
    own = lambda c: c.get("data", {}).get("displayVersion", "")  # noqa: E731
    if game != "chunithm":
        return own
    song_version: dict[str, str] = {}
    for c in charts:
        if c["difficulty"] == "MASTER" and own(c):
            song_version[c["songID"]] = own(c)
    return lambda c: song_version.get(c["songID"]) or own(c)


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
            version = _chart_versions(game, seeds[f"charts-{game}"])
            for c in seeds[f"charts-{game}"]:
                cs = by_song.get(c["songID"])
                if cs is None:
                    continue
                cs.charts.append(CatalogChart(c["difficulty"], str(c["level"]), float(c["levelNum"]), version(c)))
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
                    display_version=version(c),
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
        """Download the seeds (daily), keep only the fields we use in one small file, and load it.

        The full seeds are about 9MB of JSON; parsing them all at once leaves tens of MB of
        fragmented memory behind, so they are slimmed one file at a time and only the slim
        file (under 3MB) is read at startup.
        """
        cache = Path(cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        slim_path = cache / SLIM_NAME
        stale = not slim_path.exists() or time.time() - slim_path.stat().st_mtime > REFRESH_SECONDS
        if stale:
            try:
                slim = {}
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
                    for n in SEED_NAMES:
                        # to disk, then read one item at a time (low memory)
                        raw = cache / f"{n}.download"
                        await download_to(s, f"{base_url}/{n}.json", raw)
                        slim[n] = [slim_item(n, r) for r in iter_items(raw)]
                        raw.unlink()
                _write_slim(slim_path, slim)
                del slim
                log.info("song database updated")
            except Exception:
                log.exception("failed to download song database; using cached copy if any")
                if not slim_path.exists() and all((cache / f"{n}.json").exists() for n in SEED_NAMES):
                    # full seeds cached by an older version
                    _write_slim(slim_path, {n: [slim_item(n, r) for r in iter_items(cache / f"{n}.json")]
                                            for n in SEED_NAMES})
        if not slim_path.exists():
            log.warning("song database is unavailable; chart constants will be estimated")
            return
        # drop the old data before reading the new, so the two are never in memory together
        self.chunithm.clear()
        self.chunithm_titles.clear()
        self.catalog = {"chunithm": [], "maimai": []}
        self.maimai.clear()
        gc.collect()
        seeds = json.loads(slim_path.read_text(encoding="utf-8"))
        self.load(seeds)
        del seeds
        log.info("song database loaded: %d CHUNITHM charts, %d maimai charts",
                 len(self.chunithm), sum(len(v) for v in self.maimai.values()))


SEED_NAMES = ["songs-chunithm", "charts-chunithm", "songs-maimaidx", "charts-maimaidx"]
SLIM_NAME = "songdb.slim.json"


def slim_item(name: str, r: dict) -> dict:
    """Only the fields SongDB.load reads."""
    data = r.get("data", {})
    if name.startswith("songs"):
        item = {"id": r["id"], "title": r["title"], "artist": r.get("artist", ""),
                "data": {"genre": data.get("genre", "")}}
        for k in ("altTitles", "searchTerms"):
            if r.get(k):
                item[k] = r[k]
        return item
    return {"songID": r["songID"], "difficulty": r["difficulty"], "level": r["level"], "levelNum": r["levelNum"],
            "data": {"displayVersion": data.get("displayVersion", ""), "inGameID": data.get("inGameID")}}


def slim_seed(name: str, rows: list[dict]) -> list[dict]:
    return [slim_item(name, r) for r in rows]


def _write_slim(path: Path, slim: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(slim, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


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
