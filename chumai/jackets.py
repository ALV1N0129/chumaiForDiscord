"""Song jacket images, located via SEGA's official song lists and cached on disk."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import unicodedata
from pathlib import Path

import aiohttp

from . import tls
from .songdb import normalize_genre, normalize_title

log = logging.getLogger(__name__)

CHUNITHM_MUSIC_JSON = "https://chunithm.sega.jp/storage/json/music.json"
MAIMAI_SONGS_JSON = "https://maimai.sega.jp/data/maimai_songs.json"
CHUNITHM_IMG_BASES = [
    "https://new.chunithm-net.com/chuni-mobile/html/mobile/img/",
    "https://chunithm-net-eng.com/mobile/img/",
]
MAIMAI_IMG_BASES = [
    "https://maimaidx-eng.com/maimai-mobile/img/Music/",
    "https://maimaidx.jp/maimai-mobile/img/Music/",
]
REFRESH_SECONDS = 24 * 60 * 60
RETRY_FAILED_SECONDS = 10 * 60  # a jacket that failed to download is tried again after this


class JacketStore:
    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.chunithm: dict[int, str] = {}  # music id -> image file name
        self.maimai: dict[str, list[tuple[str, str]]] = {}  # title -> [(genre, image file name)]
        # levels of the unrated charts, from the same official lists: title -> "狂☆5" / "12+?"
        self.we_levels: dict[str, str] = {}
        self.utage_levels: dict[str, str] = {}
        self._failed: dict[str, float] = {}  # image name -> when it last failed to download
        self._errors: dict[str, str] = {}  # first URL tried -> why the download last failed, for the log

    # ---------------------------------------------------------------- index

    def load_index(self, chunithm_music: list[dict], maimai_songs: list[dict]) -> None:
        self.chunithm, self.we_levels = {}, {}
        for m in chunithm_music:
            if m.get("we_kanji") and m.get("title"):  # WORLD'S END: an attribute kanji and 1~5 stars
                self.we_levels[normalize_title(str(m["title"]))] = f"{m['we_kanji']}☆{m.get('we_star') or '?'}"
            try:
                if m.get("image"):
                    self.chunithm[int(m["id"])] = str(m["image"])
            except (KeyError, TypeError, ValueError):
                continue
        self.maimai, self.utage_levels = {}, {}
        for s in maimai_songs:
            if s.get("title") is None or not s.get("image_url"):
                continue
            if s.get("lev_utage"):  # 宴: titles like "[協]Love You"; the play log may leave the [協] out
                title = str(s["title"])
                self.utage_levels[normalize_title(title)] = str(s["lev_utage"])
                self.utage_levels.setdefault(normalize_title(re.sub(r"^\[.\]", "", title)), str(s["lev_utage"]))
            genre = unicodedata.normalize("NFKC", str(s.get("catcode", "")))
            self.maimai.setdefault(normalize_title(str(s["title"])), []).append((genre, str(s["image_url"])))

    def unrated_level(self, title: str, difficulty: str) -> str | None:
        """Official level of a WORLD'S END ("狂☆5") or 宴 ("12+?") chart."""
        levels = self.we_levels if difficulty == "WORLD'S END" else self.utage_levels
        return levels.get(normalize_title(title))

    def image_name(self, game: str, key) -> str | None:
        if game == "chunithm":
            return self.chunithm.get(int(key)) if key is not None else None
        title, genre = key
        found = self.maimai.get(normalize_title(title))
        if not found:
            return None
        if len(found) > 1 and genre:
            g = normalize_genre(genre)
            for cat, image in found:
                if cat == g:
                    return image
        return found[0][1]

    async def load_or_update(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        sources = {"chunithm_music.json": CHUNITHM_MUSIC_JSON, "maimai_songs.json": MAIMAI_SONGS_JSON}
        async with self._session() as s:
            for name, url in sources.items():
                path = self.cache_dir / name
                if path.exists() and time.time() - path.stat().st_mtime < REFRESH_SECONDS:
                    continue
                data = await self._download(s, [url])
                if data is None:
                    log.warning("could not download %s; jackets may be missing", url)
                    continue
                try:
                    json.loads(data)
                except ValueError:
                    log.warning("%s did not return JSON", url)
                    continue
                path.write_bytes(data)

        def read(name: str) -> list[dict]:
            path = self.cache_dir / name
            try:
                return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else []
            except ValueError:
                return []

        self.load_index(read("chunithm_music.json"), read("maimai_songs.json"))
        log.info("jacket index loaded: %d CHUNITHM, %d maimai", len(self.chunithm), len(self.maimai))

    # --------------------------------------------------------------- images

    def _session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=tls.SSL_CONTEXT, limit=8),
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "Mozilla/5.0 (chumaiForDiscord)"},
        )

    async def _download(self, session: aiohttp.ClientSession, urls: list[str]) -> bytes | None:
        key = urls[0]  # downloads run together: keep each one's last error apart
        self._errors.pop(key, None)
        for url in urls:
            for attempt in range(2):
                try:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            return await resp.read()
                        # maimaidx-eng.com now and then answers 404 for images it has: retry that too
                        busy = resp.status in (404, 429) or resp.status >= 500
                        self._errors[key] = f"HTTP {resp.status} from {url.split('/')[2]}"
                    if busy and attempt == 0:  # the server had a moment: wait a little, once more
                        await asyncio.sleep(1)
                        continue
                    break
                except aiohttp.ClientConnectorCertificateError as e:
                    if attempt == 0 and await tls.add_missing_intermediate(e.host, e.port or 443):
                        continue
                    break
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    self._errors[key] = f"{type(e).__name__} from {url.split('/')[2]}"
                    if attempt == 0:  # a dropped connection or a slow reply: once more
                        continue
                    break
        return None

    async def fetch(self, game: str, keys: list) -> dict[int, Path]:
        """Return {index in `keys`: local jacket path} for the jackets that could be found."""
        bases = CHUNITHM_IMG_BASES if game == "chunithm" else MAIMAI_IMG_BASES
        folder = self.cache_dir / game
        folder.mkdir(parents=True, exist_ok=True)
        result: dict[int, Path] = {}
        todo: dict[str, list[int]] = {}
        for i, key in enumerate(keys):
            name = self.image_name(game, key)
            if not name or "/" in name or "\\" in name:
                continue
            path = folder / name
            if path.exists():
                result[i] = path
            elif time.time() - self._failed.get(name, 0) > RETRY_FAILED_SECONDS:
                todo.setdefault(name, []).append(i)

        if todo:
            async with self._session() as s:

                async def one(name: str) -> None:
                    data = await self._download(s, [b + name for b in bases])
                    if data is None:
                        log.warning("jacket %s: download failed (%s); retrying in %d min", name,
                                    self._errors.pop(bases[0] + name, None), RETRY_FAILED_SECONDS // 60)
                        self._failed[name] = time.time()  # not for good: the network may just have hiccuped
                        return
                    self._failed.pop(name, None)
                    (folder / name).write_bytes(data)
                    for i in todo[name]:
                        result[i] = folder / name

                await asyncio.gather(*(one(n) for n in todo))
        return result
