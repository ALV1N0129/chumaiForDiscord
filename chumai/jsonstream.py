"""Download big JSON arrays to disk and read them one item at a time.

Parsing a multi-MB JSON file in one go needs several times its size in memory, which is too much
on small hosts (128MB). With ijson the items are read one by one; without it, plain json is used.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import aiohttp


async def download_to(session: aiohttp.ClientSession, url: str, path: Path) -> None:
    """Stream `url` into `path` (written to a temporary name first)."""
    tmp = path.with_name(path.name + ".part")
    async with session.get(url) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as f:
            async for chunk in resp.content.iter_chunked(1 << 16):
                f.write(chunk)
    tmp.replace(path)


def iter_items(path: Path) -> Iterator[dict]:
    """The items of a top-level JSON array, one at a time."""
    try:
        import ijson
    except ImportError:
        yield from json.loads(path.read_bytes())
        return
    with path.open("rb") as f:
        yield from ijson.items(f, "item", use_float=True)
