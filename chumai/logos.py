"""Download game logos from URLs set in .env and cache them as PNG."""

from __future__ import annotations

import io
import logging
from pathlib import Path

import aiohttp
from PIL import Image

from . import tls

log = logging.getLogger(__name__)


async def _get(session: aiohttp.ClientSession, url: str) -> bytes:
    for attempt in range(2):
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.read()
        except aiohttp.ClientConnectorCertificateError as e:
            if attempt == 0 and await tls.add_missing_intermediate(e.host, e.port or 443):
                continue
            raise
    raise AssertionError("unreachable")


async def download_logos(logo_dir: str | Path, urls: dict[str, str | None]) -> None:
    """Save each game's logo to <logo_dir>/<game>.png, re-downloading only when the URL changes."""
    folder = Path(logo_dir)
    todo = {}
    for game, url in urls.items():
        if not url:
            continue
        marker = folder / f"{game}.url"
        if (folder / f"{game}.png").exists() and marker.exists() and marker.read_text().strip() == url:
            continue
        todo[game] = url
    if not todo:
        return

    folder.mkdir(parents=True, exist_ok=True)
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=tls.SSL_CONTEXT),
        timeout=aiohttp.ClientTimeout(total=30),
        headers={"User-Agent": "Mozilla/5.0 (chumaiForDiscord)"},
    ) as s:
        for game, url in todo.items():
            try:
                data = await _get(s, url)
                with Image.open(io.BytesIO(data)) as im:
                    im.convert("RGBA").save(folder / f"{game}.png")
                (folder / f"{game}.url").write_text(url)
                log.info("downloaded %s logo", game)
            except Exception:
                log.exception("could not download the %s logo from %s (PNG/JPG/WebP only)", game, url)
