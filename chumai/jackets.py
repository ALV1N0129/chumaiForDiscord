"""Song jacket images, located via SEGA's official song lists and cached on disk.

SEGA's images are 190x190. Larger ones (maimai 400x400, CHUNITHM 300x300) come from LXNS
(maimai.lxns.net, a score tracker for the Chinese versions) when it has the song; they're saved
shrunk to HQ_SIZE as JPEG, so they take little room on disk and in memory."""

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
# larger jackets: CHUNITHM by music id, maimai by LXNS's song id (looked up by title)
LXNS_CHUNITHM_JACKET = "https://assets2.lxns.net/chunithm/jacket/{}.png"
LXNS_MAIMAI_JACKET = "https://assets2.lxns.net/maimai/jacket/{}.png"
LXNS_MAIMAI_SONGS = "https://maimai.lxns.net/api/v0/maimai/song/list"
HQ_SIZE = 300  # saved at most this big (maimai's 400 shrunk): sharper than SEGA's 190, still small
REFRESH_SECONDS = 24 * 60 * 60
RETRY_FAILED_SECONDS = 10 * 60  # a jacket that failed to download is tried again after this


_LXNS_SONG = re.compile(r'\{"id":(\d+),"title":"((?:[^"\\]|\\.)*)","artist":')


def lxns_ids(text: str) -> dict[str, int]:
    """LXNS's maimai song list -> {normalized title: song id}, read with a pattern instead of parsed
    whole (memory). A title with more than one id is left out (can't tell which)."""
    ids: dict[str, int] = {}
    twice: set[str] = set()
    for sid, raw in _LXNS_SONG.findall(text):
        try:
            title = normalize_title(json.loads(f'"{raw}"'))
        except ValueError:
            continue
        sid = int(sid) % 10000  # the DX chart of a song is 10000 + its id; same jacket
        if ids.get(title, sid) != sid:
            twice.add(title)
        ids[title] = sid
    for title in twice:
        del ids[title]
    return ids


def shrink_jacket(data: bytes, size: int = HQ_SIZE) -> bytes:
    """A jacket image at most `size` square, as JPEG."""
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(data)) as im:
        im = im.convert("RGB")
        if im.width > size:
            im = im.resize((size, size), Image.LANCZOS)
        out = BytesIO()
        im.save(out, "JPEG", quality=95, subsampling=0)  # close to lossless
        im.close()
    return out.getvalue()


def _we_stars(value) -> str:
    """music.json's we_star is 1, 3, 5, 7 or 9 for ☆1 to ☆5."""
    try:
        return str((int(value) + 1) // 2)
    except (TypeError, ValueError):
        return "?"


class JacketStore:
    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.chunithm: dict[int, str] = {}  # music id -> image file name
        self.maimai: dict[str, list[tuple[str, str]]] = {}  # title -> [(genre, image file name)]
        # levels of the unrated charts, from the same official lists: title -> "狂☆5" / "12+?"
        self.we_levels: dict[str, str] = {}
        self.utage_levels: dict[str, str] = {}
        # official readings (katakana, for the guessing games): (game, title) -> readings
        self.readings: dict[tuple[str, str], list[str]] = {}
        self.lxns_maimai: dict[str, int] = {}  # normalized title -> LXNS song id (titles with one id only)
        self._failed: dict[str, float] = {}  # image name -> when it last failed to download
        self._hq_missing: set[str] = set()  # larger jackets LXNS doesn't have (asked once per run)
        self._shrink: asyncio.Lock | None = None  # one image decoded at a time (memory)
        self._errors: dict[str, str] = {}  # first URL tried -> why the download last failed, for the log

    # ---------------------------------------------------------------- index

    def load_index(self, chunithm_music: list[dict], maimai_songs: list[dict]) -> None:
        self.chunithm, self.we_levels, self.readings = {}, {}, {}
        for game, songs, field_name in (("chunithm", chunithm_music, "reading"), ("maimai", maimai_songs, "title_kana")):
            for m in songs:
                if m.get("title") and m.get(field_name):
                    found = self.readings.setdefault((game, normalize_title(str(m["title"]))), [])
                    if str(m[field_name]) not in found:
                        found.append(str(m[field_name]))
        for m in chunithm_music:
            if m.get("we_kanji") and m.get("title"):  # WORLD'S END: an attribute kanji and 1~5 stars
                self.we_levels[normalize_title(str(m["title"]))] = f"{m['we_kanji']}☆{_we_stars(m.get('we_star'))}"
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

    def reading(self, game: str, title: str) -> list[str]:
        return self.readings.get((game, normalize_title(title)), [])

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
        sources = {"chunithm_music.json": CHUNITHM_MUSIC_JSON, "maimai_songs.json": MAIMAI_SONGS_JSON,
                   "lxns_maimai_ids.json": LXNS_MAIMAI_SONGS}
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
                    if name.startswith("lxns"):  # big: kept only as {title: id}, read with a pattern
                        if not data.startswith(b'{"songs":'):
                            raise ValueError
                        data = json.dumps(lxns_ids(data.decode("utf-8")), ensure_ascii=False).encode()
                    else:
                        json.loads(data)
                except ValueError:
                    log.warning("%s did not return JSON", url)
                    continue
                path.write_bytes(data)
                del data

        def read(name: str) -> list[dict]:
            path = self.cache_dir / name
            try:
                return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else []
            except ValueError:
                return []

        self.load_index(read("chunithm_music.json"), read("maimai_songs.json"))
        found = read("lxns_maimai_ids.json")
        self.lxns_maimai = found if isinstance(found, dict) else {}
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

    def key_of_image(self, game: str, name: str):
        """The song key (as image_name takes) of a SEGA jacket image name, for the play log's
        jackets; None if unknown."""
        if game == "chunithm":
            return next((mid for mid, image in self.chunithm.items() if image == name), None)
        return next(((title, genre) for title, found in self.maimai.items() for genre, image in found
                     if image == name), None)

    def hq_url(self, game: str, key) -> str | None:
        """Where LXNS has a larger copy of the jacket, if it might."""
        if game == "chunithm":
            return LXNS_CHUNITHM_JACKET.format(int(key)) if key is not None else None
        sid = self.lxns_maimai.get(normalize_title(key[0]))
        return LXNS_MAIMAI_JACKET.format(sid) if sid is not None else None

    async def _fetch_hq(self, game: str, keys: list, folder: Path) -> dict[int, Path]:
        """The larger jackets: from the cache, else LXNS (saved shrunk to HQ_SIZE)."""
        result: dict[int, Path] = {}
        todo: dict[str, list[int]] = {}
        for i, key in enumerate(keys):
            url = self.hq_url(game, key)
            if url is None or url in self._hq_missing:
                continue
            path = folder / f"hq_{url.rsplit('/', 1)[1].split('.')[0]}.jpg"
            if path.exists():
                result[i] = path
            else:
                todo.setdefault(url, []).append(i)
        if not todo:
            return result
        folder.mkdir(parents=True, exist_ok=True)
        gate = asyncio.Semaphore(4)  # a few at a time: each is held in memory until shrunk
        async with self._session() as s:

            async def one(url: str) -> None:
                async with gate:
                    await get(url)

            async def get(url: str) -> None:
                try:
                    async with s.get(url) as resp:
                        data = await resp.read() if resp.status == 200 else None
                        if resp.status == 404:
                            self._hq_missing.add(url)
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    data = None
                if not data:
                    return
                if self._shrink is None:
                    self._shrink = asyncio.Lock()
                async with self._shrink:
                    try:
                        small = await asyncio.to_thread(shrink_jacket, data)
                    except Exception:
                        self._hq_missing.add(url)
                        return
                path = folder / f"hq_{url.rsplit('/', 1)[1].split('.')[0]}.jpg"
                path.write_bytes(small)
                for i in todo[url]:
                    result[i] = path

            await asyncio.gather(*(one(u) for u in todo))
        return result

    async def fetch(self, game: str, keys: list) -> dict[int, Path]:
        """Return {index in `keys`: local jacket path} for the jackets that could be found: the larger
        copy when LXNS has it, else SEGA's."""
        bases = CHUNITHM_IMG_BASES if game == "chunithm" else MAIMAI_IMG_BASES
        folder = self.cache_dir / game
        folder.mkdir(parents=True, exist_ok=True)
        result = await self._fetch_hq(game, keys, folder)
        todo: dict[str, list[int]] = {}
        for i, key in enumerate(keys):
            if i in result:
                continue
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
