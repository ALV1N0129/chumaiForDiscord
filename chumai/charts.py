"""CHUNITHM chart views from sdvx.in, for the chart guessing game.

Which sdvx.in page belongs to which song comes from chuni-penguin's song data
(https://github.com/beer-psi/chuni-penguin, BSD Zero Clause License), matched by the
in-game song id. The chart images themselves are downloaded from sdvx.in when needed
and cached on disk. maimai has no such data, so this is CHUNITHM only.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import random
import time
from pathlib import Path

import aiohttp
from PIL import Image

from .jsonstream import download_to, iter_items

log = logging.getLogger(__name__)

INDEX_URL = ("https://raw.githubusercontent.com/beer-psi/chuni-penguin/develop/"
             "chuni_penguin/database/seeds/songs.json")
REFRESH_SECONDS = 7 * 24 * 60 * 60
SDVX = "https://sdvx.in/chunithm"

# our difficulty names -> chuni-penguin's
DIFFS = {"BASIC": "BAS", "ADVANCED": "ADV", "EXPERT": "EXP", "MASTER": "MAS", "ULTIMA": "ULT"}


def build_index(songs) -> dict[str, str]:
    """chuni-penguin songs.json -> {"<song id>/<difficulty>": sdvx.in id}."""
    index = {}
    for song in songs:
        for chart in song.get("charts", []):
            view = chart.get("sdvxin")
            if view and view.get("id") and chart.get("difficulty") in DIFFS.values():
                index[f"{song['id']}/{chart['difficulty']}"] = str(view["id"])
    return index


def view_urls(sdvx_id: str, difficulty: str) -> tuple[list[str], list[str], list[str]]:
    """Candidate URLs for the (background, notes, bar lines) layers of a chart view."""
    folder = f"{SDVX}/{sdvx_id[:2]}"
    if difficulty == "ULT":
        return ([f"{SDVX}/ult/bg/{sdvx_id}bg.png", f"{folder}/bg/{sdvx_id}bg.png"],
                [f"{SDVX}/ult/obj/data{sdvx_id}ult.png"],
                [f"{SDVX}/ult/bg/{sdvx_id}bar.png", f"{folder}/bg/{sdvx_id}bar.png"])
    name = "mst" if difficulty == "MAS" else difficulty.lower()
    return ([f"{folder}/bg/{sdvx_id}bg.png"], [f"{folder}/obj/data{sdvx_id}{name}.png"],
            [f"{folder}/bg/{sdvx_id}bar.png"])


def fit_layer(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Put a layer on a transparent canvas of `size` (the layers can differ in size)."""
    if img.size == size:
        return img
    box = Image.new("RGBA", size, (0, 0, 0, 0))
    box.paste(img, (0, 0), img)
    return box


def page_url(sdvx_id: str, difficulty: str) -> str:
    """The chart's page on sdvx.in."""
    if difficulty == "ULT":
        return f"{SDVX}/ult/{sdvx_id}ult.htm"
    name = {"MAS": "mst", "BAS": "bsc"}.get(difficulty, difficulty.lower())
    return f"{SDVX}/{sdvx_id[:2]}/{sdvx_id}{name}.htm"


def _layer(data: bytes, size: tuple[int, int] | None = None) -> Image.Image:
    with Image.open(io.BytesIO(data)) as im:
        img = im.convert("RGBA")
    return fit_layer(img, size) if size else img


def compose(bg: bytes, notes: bytes, bar: bytes) -> Image.Image:
    base = _layer(bg)
    out = Image.alpha_composite(Image.new("RGBA", base.size, (0, 0, 0, 255)), base)
    out = Image.alpha_composite(out, _layer(notes, base.size))
    return Image.alpha_composite(out, _layer(bar, base.size)).convert("RGB")


def crop_hint(view: Image.Image, notes: Image.Image | None, rng: random.Random, share: float = 0.2) -> Image.Image:
    """A vertical strip of the chart, picking the busiest of a few random spots."""
    w, h = view.size
    sw = max(1, min(w, max(160, int(w * share))))
    candidates = [rng.randint(0, w - sw) for _ in range(8)] if w > sw else [0]
    if notes is not None:
        alpha = notes.getchannel("A")
        candidates.sort(key=lambda x: -sum(alpha.crop((x, 0, x + sw, h)).histogram()[16:]))
    x = candidates[0]
    strip = view.crop((x, 0, x + sw, h))
    if strip.height > 900:
        strip = strip.resize((max(1, strip.width * 900 // strip.height), 900), Image.LANCZOS)
    return strip


class ChartViews:
    def __init__(self, cache_dir: str | Path):
        self.dir = Path(cache_dir)
        self.index: dict[str, str] = {}
        self._failed: set[str] = set()

    def sdvx_id(self, music_id: int | None, difficulty: str) -> str | None:
        short = DIFFS.get(difficulty)
        if music_id is None or short is None:
            return None
        return self.index.get(f"{music_id}/{short}")

    async def load_or_update(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / "sdvxin.json"
        if not path.exists() or time.time() - path.stat().st_mtime > REFRESH_SECONDS:
            try:
                raw = self.dir / "songs.download"
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as s:
                    await download_to(s, INDEX_URL, raw)  # 7MB: read song by song, not all at once
                path.write_text(json.dumps(build_index(iter_items(raw))), encoding="utf-8")
                raw.unlink()
                log.info("chart view index updated")
            except Exception:
                log.exception("failed to download the chart view index; using cached copy if any")
        if path.exists():
            self.index = json.loads(path.read_text(encoding="utf-8"))

    async def _get(self, session: aiohttp.ClientSession, urls: list[str]) -> bytes:
        for url in urls:
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.read()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                continue
        raise LookupError(urls[0])

    async def fetch(self, music_id: int | None, difficulty: str) -> tuple[Path, Path] | None:
        """(composed chart view, notes layer) on disk, downloading them the first time."""
        sid = self.sdvx_id(music_id, difficulty)
        if sid is None:
            return None
        short = DIFFS[difficulty]
        folder = self.dir / "views"
        view_path, notes_path = folder / f"{sid}{short}.jpg", folder / f"{sid}{short}_notes.png"
        if view_path.exists() and notes_path.exists():
            return view_path, notes_path
        if f"{sid}{short}" in self._failed:
            return None
        bg_urls, note_urls, bar_urls = view_urls(sid, short)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60),
                                             headers={"User-Agent": "Mozilla/5.0 (chumaiForDiscord)"}) as s:
                bg, notes, bar = await asyncio.gather(self._get(s, bg_urls), self._get(s, note_urls),
                                                      self._get(s, bar_urls))
            view = await asyncio.to_thread(compose, bg, notes, bar)
        except Exception:
            log.warning("could not load chart view %s %s", sid, short, exc_info=True)
            self._failed.add(f"{sid}{short}")
            return None
        folder.mkdir(parents=True, exist_ok=True)
        view.save(view_path, "JPEG", quality=92)
        notes_path.write_bytes(notes)
        return view_path, notes_path
