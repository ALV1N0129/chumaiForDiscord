"""How hard maimai charts really are, from diving-fish's player statistics (for /recommend).

diving-fish (https://www.diving-fish.com/maimaidx/prober/) fits a "real" constant (fit_diff) to
every chart from its players' scores. A chart whose fit_diff is below its official constant plays
easier than its number: the "꿀곡" everyone recommends. We keep only
{(title, difficulty): official constant - fit_diff} for charts with enough plays.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from pathlib import Path

import aiohttp

from .jsonstream import download_to, iter_items
from .songdb import normalize_title

log = logging.getLogger(__name__)

BASE_URL = "https://www.diving-fish.com/api/maimaidxprober"
REFRESH_SECONDS = 7 * 24 * 60 * 60
SLIM_NAME = "chartstats.json"
MIN_PLAYS = 50  # fewer players than this and the fit is noise
MAX_DELTA = 1.0  # clamp: a fit this far off is more likely a mismatch than a real chart
DIFFS = ["Basic", "Advanced", "Expert", "Master", "Re:Master"]


def _chart_stats(path: Path) -> Iterator[tuple[str, list]]:
    """(song id, per-difficulty stats) from chart_stats.json, one song at a time."""
    try:
        import ijson
    except ImportError:
        yield from json.loads(path.read_bytes()).get("charts", {}).items()
        return
    with path.open("rb") as f:
        yield from ijson.kvitems(f, "charts", use_float=True)


def build(music: Iterator[dict], stats: Iterator[tuple[str, list]]) -> dict[str, list[float]]:
    """{"<normalized title>\\t<difficulty>": [official constant - fit_diff, plays]}"""
    songs = {}
    for song in music:
        if song.get("type") not in ("SD", "DX") or not song.get("title") or int(song.get("id") or 0) >= 100000:
            continue  # 宴 (utage) charts have ids from 100000
        prefix = "DX " if song["type"] == "DX" else ""
        songs[str(song.get("id"))] = (normalize_title(song["title"]), prefix, song.get("ds") or [])
    out: dict[str, list[float]] = {}
    for song_id, charts in stats:
        if song_id not in songs or not isinstance(charts, list):
            continue
        title, prefix, ds = songs[song_id]
        for i, chart in enumerate(charts[: len(DIFFS)]):
            if not isinstance(chart, dict) or i >= len(ds):
                continue
            fit, plays = chart.get("fit_diff"), chart.get("cnt") or 0
            if fit is None or plays < MIN_PLAYS:
                continue
            delta = max(-MAX_DELTA, min(MAX_DELTA, float(ds[i]) - float(fit)))
            out[f"{title}\t{prefix}{DIFFS[i]}"] = [round(delta, 3), int(plays)]
    return out


class ChartStats:
    def __init__(self, cache_dir: str | Path):
        self.dir = Path(cache_dir)
        self.delta: dict[tuple[str, str], float] = {}

    def honey(self, title: str, difficulty: str) -> float | None:
        """How much easier than its constant a chart plays (negative: harder), if known."""
        return self.delta.get((normalize_title(title), difficulty))

    def load(self, data: dict[str, list[float]]) -> None:
        self.delta = {tuple(k.split("\t", 1)): v[0] for k, v in data.items()}

    async def load_or_update(self, base_url: str = BASE_URL) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / SLIM_NAME
        if not path.exists() or time.time() - path.stat().st_mtime > REFRESH_SECONDS:
            try:
                music_raw, stats_raw = self.dir / "music_data.download", self.dir / "chart_stats.download"
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as s:
                    await download_to(s, f"{base_url}/music_data", music_raw)
                    await download_to(s, f"{base_url}/chart_stats", stats_raw)
                data = build(iter_items(music_raw), _chart_stats(stats_raw))
                if not data:
                    raise ValueError("no chart statistics matched")
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                log.info("maimai chart statistics updated: %d charts", len(data))
            except Exception:
                log.exception("failed to download maimai chart statistics; using cached copy if any")
            finally:
                for p in (self.dir / "music_data.download", self.dir / "chart_stats.download"):
                    p.unlink(missing_ok=True)
        if path.exists():
            self.load(json.loads(path.read_text(encoding="utf-8")))
