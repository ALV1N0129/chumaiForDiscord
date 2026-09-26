"""Minimal async client for the Kamaitachi (Tachi) public API.

Kamaitachi is the community score tracker that supports both international and
Japanese maimai DX / CHUNITHM. Profiles are public by default, so no API key is
needed to read someone's personal bests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import aiohttp

GAMES = {
    "maimai": "maimaidx",
    "chunithm": "chunithm",
}


class TachiError(Exception):
    pass


class UserNotFound(TachiError):
    pass


@dataclass
class Song:
    id: str
    title: str
    artist: str


@dataclass
class Chart:
    id: str
    song_id: str
    difficulty: str
    level: str
    level_const: float
    display_version: str


@dataclass
class PersonalBest:
    chart_id: str
    score_data: dict[str, Any]
    calculated: dict[str, Any] = field(default_factory=dict)


@dataclass
class PBBundle:
    username: str
    pbs: list[PersonalBest]
    charts: dict[str, Chart]
    songs: dict[str, Song]


def _get_id(doc: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        if doc.get(k) is not None:
            return str(doc[k])
    return None


def parse_bundle(username: str, body: dict[str, Any]) -> PBBundle:
    """Turn a `pbs/all` response body into typed objects.

    Handles both the current API (chart.chartID, chart.data.displayVersion,
    optional nested chart.song) and the older one (chart.songID and
    song.data.displayVersion).
    """
    songs: dict[str, Song] = {}
    for s in body.get("songs", []):
        sid = _get_id(s, "id", "songID")
        if sid is not None:
            songs[sid] = Song(sid, s.get("title", "?"), s.get("artist", ""))

    song_versions = {
        _get_id(s, "id", "songID"): (s.get("data") or {}).get("displayVersion")
        for s in body.get("songs", [])
    }

    charts: dict[str, Chart] = {}
    for c in body.get("charts", []):
        nested = c.get("song") or {}
        sid = _get_id(c, "songID") or _get_id(nested, "id")
        if nested and sid and sid not in songs:
            songs[sid] = Song(sid, nested.get("title", "?"), nested.get("artist", ""))
        cid = _get_id(c, "chartID", "id")
        if cid is None or sid is None:
            continue
        data = c.get("data") or {}
        version = data.get("displayVersion") or song_versions.get(sid) or ""
        charts[cid] = Chart(
            id=cid,
            song_id=sid,
            difficulty=c.get("difficulty", "?"),
            level=str(c.get("level", "?")),
            level_const=float(c.get("levelNum") or 0),
            display_version=version,
        )

    pbs = [
        PersonalBest(
            chart_id=str(pb["chartID"]),
            score_data=pb.get("scoreData") or {},
            calculated=pb.get("calculatedData") or {},
        )
        for pb in body.get("pbs", [])
        if pb.get("chartID") is not None
    ]
    return PBBundle(username=username, pbs=pbs, charts=charts, songs=songs)


class TachiClient:
    def __init__(self, base_url: str = "https://kamai.tachi.ac/api/v1", api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._session: aiohttp.ClientSession | None = None

    async def _get(self, path: str) -> tuple[int, dict[str, Any]]:
        if self._session is None or self._session.closed:
            headers = {"User-Agent": "chumaiForDiscord"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._session = aiohttp.ClientSession(
                headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            )
        async with self._session.get(self.base_url + path) as resp:
            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = {}
            return resp.status, data or {}

    async def fetch_all_pbs(self, username: str, game: str) -> PBBundle:
        tachi_game = GAMES[game]
        # Newer Tachi dropped the playtype segment; older deployments still need it.
        paths = [
            f"/users/{username}/games/{tachi_game}/pbs/all",
            f"/users/{username}/games/{tachi_game}/Single/pbs/all",
        ]
        last_error = "unknown error"
        for path in paths:
            status, data = await self._get(path)
            if status == 200 and data.get("success"):
                return parse_bundle(username, data["body"])
            last_error = data.get("description") or f"HTTP {status}"
            if status == 404 and "user" in last_error.lower() and "game" not in last_error.lower():
                raise UserNotFound(last_error)
        raise TachiError(last_error)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
