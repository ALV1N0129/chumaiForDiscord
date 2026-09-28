"""Download a font that has both Korean and Japanese glyphs (Noto Sans CJK, SIL OFL).

Windows' Japanese fonts (Yu Gothic, Meiryo) have no Hangul, so Korean labels would show as boxes.
"""

from __future__ import annotations

import logging
from pathlib import Path

import aiohttp

log = logging.getLogger(__name__)

FONT_NAME = "NotoSansCJKkr-Bold.otf"
FONT_URL = f"https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/Korean/{FONT_NAME}"


async def ensure_font(font_dir: str | Path, url: str = FONT_URL) -> Path | None:
    """<font_dir>/NotoSansCJKkr-Bold.otf, downloading it (about 17MB) the first time."""
    path = Path(font_dir) / FONT_NAME
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    try:
        log.info("downloading the Korean/Japanese font (about 17MB, first run only)...")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as s:
            async with s.get(url) as resp:
                resp.raise_for_status()
                with tmp.open("wb") as f:
                    async for chunk in resp.content.iter_chunked(1 << 16):
                        f.write(chunk)
        tmp.replace(path)
        log.info("font saved to %s", path)
        return path
    except Exception:
        log.exception("could not download the font; Korean text may not show correctly")
        tmp.unlink(missing_ok=True)
        return None
