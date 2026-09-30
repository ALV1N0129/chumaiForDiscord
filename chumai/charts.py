"""CHUNITHM community nicknames from chuni-penguin's song data
(https://github.com/beer-psi/chuni-penguin, BSD Zero Clause License), for the jacket guessing game.
The song data is a 7MB file, so it is read song by song and only the nicknames are kept."""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

import aiohttp

from .jsonstream import download_to, iter_items

log = logging.getLogger(__name__)

INDEX_URL = ("https://raw.githubusercontent.com/beer-psi/chuni-penguin/develop/"
             "chuni_penguin/database/seeds/songs.json")
REFRESH_SECONDS = 7 * 24 * 60 * 60
ALIASES_NAME = "aliases.json"  # {title: [nickname]}


def collect_aliases(songs) -> dict[str, list[str]]:
    """chuni-penguin songs.json -> {title: [community nickname]}."""
    return {song["title"]: [str(a) for a in song["aliases"] if a]
            for song in songs if song.get("aliases") and song.get("title")}


class PenguinNicknames:
    def __init__(self, cache_dir: str | Path):
        self.dir = Path(cache_dir)

    @property
    def path(self) -> Path:
        return self.dir / ALIASES_NAME

    async def load_or_update(self) -> None:
        """Download the nicknames when missing or a week old (a failure keeps the saved copy)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        # left from the removed /chart: sdvx.in's chart images and their index
        shutil.rmtree(self.dir / "views", ignore_errors=True)
        (self.dir / "sdvxin.json").unlink(missing_ok=True)
        if self.path.exists() and time.time() - self.path.stat().st_mtime < REFRESH_SECONDS:
            return
        try:
            raw = self.dir / "songs.download"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as s:
                await download_to(s, INDEX_URL, raw)
            self.path.write_text(json.dumps(collect_aliases(iter_items(raw)), ensure_ascii=False), encoding="utf-8")
            raw.unlink()
            log.info("chuni-penguin nicknames updated")
        except Exception:
            log.exception("failed to download chuni-penguin nicknames; using cached copy if any")
