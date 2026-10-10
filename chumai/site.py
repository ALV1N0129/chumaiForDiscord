"""mai records (maimai record site, e.g. https://mai.alv1n.fyi) link: /site link·unlink·sync.

Once someone links their Discord account to a site account (a code from the site's settings):

- their maimai records go up to the site, read with their SEGA login like /b50 does: with /site sync,
  after a new credit shows up in their play log, and every so often when their play count went up;
- /favorite keeps presets on the site instead of here, so the site and the bot share them;
- the site's "apply to the game" button leaves a job the bot picks up here and does on maimai DX NET.

Needs SITE_BOT_SECRET (the same value as BOT_SECRET on the site). SITE_URL is the site's address."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

from . import net_parsers, site_payload
from .segaid import NetClient, SegaError

if TYPE_CHECKING:
    from .bot import ChumaiBot

log = logging.getLogger(__name__)

DEFAULT_URL = "https://mai.alv1n.fyi"
LINK_CACHE_SECONDS = 60
AMBIGUOUS_CACHE_SECONDS = 12 * 60 * 60


def _sync_minutes() -> float:
    """How often linked records are checked for new plays: SITE_SYNC_MINUTES, 30 by default, 10 at least."""
    try:
        return max(10.0, float(os.environ.get("SITE_SYNC_MINUTES") or 30))
    except ValueError:
        return 30.0


class SiteError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class SiteClient:
    """The site's bot API (Authorization: Bot <secret>, X-Discord-User: <id>)."""

    def __init__(self, url: str, secret: str | None):
        self.url = url.rstrip("/")
        self.secret = secret
        self._session: aiohttp.ClientSession | None = None
        self._linked: dict[int, tuple[float, str | None]] = {}
        self._ambiguous: tuple[float, set[str]] | None = None

    @classmethod
    def from_env(cls) -> "SiteClient":
        return cls(os.environ.get("SITE_URL") or DEFAULT_URL, os.environ.get("SITE_BOT_SECRET") or None)

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.secret)

    def profile_url(self, username: str) -> str:
        return f"{self.url}/u/{username}"

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60),
                                                  headers={"User-Agent": "chumaiForDiscord"})
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    async def call(self, method: str, path: str, discord_id: int | None = None, body=None, params=None) -> dict:
        if not self.enabled:
            raise SiteError("사이트 연동이 꺼져 있어요 (봇 설정에 SITE_BOT_SECRET 이 없어요).")
        headers = {"Authorization": f"Bot {self.secret}"}
        if discord_id is not None:
            headers["X-Discord-User"] = str(discord_id)
        session = await self._http()
        try:
            async with session.request(method, self.url + path, json=body, params=params, headers=headers) as resp:
                data = await resp.json(content_type=None)
                status = resp.status
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            raise SiteError(f"사이트에 연결하지 못했어요 ({type(e).__name__}).") from e
        if status >= 400:
            message = data.get("error") if isinstance(data, dict) else None
            raise SiteError(message or f"사이트 오류 (HTTP {status})", status)
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------ accounts

    async def username(self, discord_id: int) -> str | None:
        """The site account linked to this Discord user (cached for a minute), or None."""
        if not self.enabled:
            return None
        cached = self._linked.get(discord_id)
        if cached and cached[0] > time.time():
            return cached[1]
        try:
            name = (await self.call("GET", "/api/bot/user", discord_id)).get("username")
        except SiteError as e:
            if e.status != 404:
                raise
            name = None
        self._linked[discord_id] = (time.time() + LINK_CACHE_SECONDS, name)
        return name

    async def link(self, discord_id: int, code: str) -> str:
        data = await self.call("POST", "/api/bot/link", body={"code": code, "discordId": str(discord_id)})
        self._linked[discord_id] = (time.time() + LINK_CACHE_SECONDS, data["username"])
        return data["username"]

    async def unlink(self, discord_id: int) -> bool:
        data = await self.call("POST", "/api/bot/unlink", body={"discordId": str(discord_id)})
        self._linked.pop(discord_id, None)
        return bool(data.get("ok"))

    async def users(self) -> list[dict]:
        return (await self.call("GET", "/api/bot/users")).get("users", [])

    # ------------------------------------------------------------------ records

    async def ambiguous(self) -> set[str]:
        """Song keys that share a title with another song (told apart by artist), from the site."""
        if self._ambiguous and self._ambiguous[0] > time.time():
            return self._ambiguous[1]
        session = await self._http()
        try:
            async with session.get(f"{self.url}/data/ambiguous.json") as resp:
                keys = set(await resp.json(content_type=None)) if resp.status == 200 else set()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
            keys = self._ambiguous[1] if self._ambiguous else set()
        self._ambiguous = (time.time() + AMBIGUOUS_CACHE_SECONDS, keys)
        return keys

    async def upload(self, discord_id: int, payload: dict) -> dict:
        return await self.call("POST", "/api/bot/upload", discord_id, body=payload)

    # ------------------------------------------------------------------ favorite presets

    async def presets(self, discord_id: int) -> list[tuple[str, list]]:
        data = await self.call("GET", "/api/bot/presets", discord_id)
        return [(p["name"], p["songs"]) for p in data.get("presets", [])]

    async def save_preset(self, discord_id: int, name: str, songs: list) -> None:
        await self.call("PUT", "/api/bot/presets", discord_id, body={"name": name, "songs": songs})

    async def delete_preset(self, discord_id: int, name: str) -> bool:
        data = await self.call("DELETE", "/api/bot/presets", discord_id, params={"name": name})
        return bool(data.get("ok"))

    # ------------------------------------------------------------------ jobs from the site

    async def jobs(self) -> list[dict]:
        return (await self.call("GET", "/api/bot/jobs")).get("jobs", [])

    async def claim(self, job_id: int) -> bool:
        return bool((await self.call("POST", f"/api/bot/jobs/{job_id}/claim")).get("ok"))

    async def finish(self, job_id: int, result: dict) -> None:
        await self.call("POST", f"/api/bot/jobs/{job_id}/result", body=result)


# --------------------------------------------------------------------------- doing things on NET


class SiteSync:
    """Uploads and site jobs for linked people. One NET job at a time per person."""

    def __init__(self, bot: "ChumaiBot", client: SiteClient):
        self.bot = bot
        self.client = client
        self._locks: dict[int, asyncio.Lock] = {}
        self._due: dict[int, float] = {}  # discord_id -> when to look for new plays next
        self._failing: set[str] = set()  # what's failing now, so it's logged once
        self._running: set[asyncio.Task] = set()

    def lock(self, discord_id: int) -> asyncio.Lock:
        return self._locks.setdefault(discord_id, asyncio.Lock())

    def _token(self, discord_id: int) -> str:
        token = self.bot.links.get_sega_token(discord_id)
        if token is None:
            raise SegaError("봇에 SEGA ID 로그인이 안 돼 있어요. `/login` 을 먼저 해 주세요.")
        return token

    def _keep_token(self, discord_id: int, net: NetClient, token: str) -> None:
        if net.clal != token:
            self.bot.links.set_sega_token(discord_id, net.clal)

    async def upload(self, discord_id: int, progress=None) -> dict:
        """Read this person's maimai records and send them to the site."""
        token = self._token(discord_id)
        ambiguous = await self.client.ambiguous()
        async with self.lock(discord_id):
            async with NetClient("maimai", token) as net:
                payload = await site_payload.collect(net, ambiguous, progress)
            self._keep_token(discord_id, net, token)
        if progress:
            await progress("사이트에 올리는 중...")
        result = await self.client.upload(discord_id, payload)
        result["charts"] = sum(1 for chart in payload["charts"] if chart[5])
        result["plays"] = len(payload["plays"])
        log.info("records sent to the site for %s (%d charts, %s changed)", discord_id, result["charts"],
                 result.get("changed"))
        return result

    def request_upload(self, discord_id: int) -> None:
        """New plays were seen (play log): upload on the next round."""
        self._due[discord_id] = 0.0

    async def sync_if_played(self, user: dict) -> None:
        """Upload when NET's play count is past what the site has."""
        discord_id = int(user["discordId"])
        token = self.bot.links.get_sega_token(discord_id)
        if token is None:
            return
        async with self.lock(discord_id):
            async with NetClient("maimai", token) as net:
                count = site_payload.play_count(await net.get("/maimai-mobile/playerData/"))
            self._keep_token(discord_id, net, token)
        known = user.get("playCount")
        if count is not None and (known is None or count > known):
            await self.upload(discord_id)

    async def auto_sync(self) -> None:
        from .bot import quiet_now

        if not self.client.enabled or quiet_now():
            return
        try:
            users = await self.client.users()
        except SiteError as e:
            self._log_once("users", "could not reach the record site: %s", e)
            return
        self._failing.discard("users")
        now = time.time()
        for user in users:
            discord_id = int(user["discordId"])
            if self._due.get(discord_id, 0.0) > now:
                continue
            self._due[discord_id] = now + _sync_minutes() * 60
            try:
                await self.sync_if_played(user)
                self._failing.discard(f"sync:{discord_id}")
            except Exception as e:
                self._log_once(f"sync:{discord_id}", "site sync failed for %s: %s", discord_id, e)

    # ------------------------------------------------------------------ jobs

    async def run_jobs(self) -> None:
        if not self.client.enabled:
            return
        try:
            jobs = await self.client.jobs()
        except SiteError as e:
            self._log_once("jobs", "could not reach the record site: %s", e)
            return
        self._failing.discard("jobs")
        for job in jobs:
            try:
                if await self.client.claim(job["id"]):
                    task = asyncio.create_task(self._run_job(job))
                    self._running.add(task)
                    task.add_done_callback(self._running.discard)
            except SiteError as e:
                log.warning("could not claim site job %s: %s", job.get("id"), e)

    async def _run_job(self, job: dict) -> None:
        from . import favorites

        discord_id = int(job["discordId"])
        try:
            token = self._token(discord_id)
            async with self.lock(discord_id):
                async with NetClient("maimai", token) as net:
                    rows = net_parsers.parse_maimai_favorites(await net.get(favorites.PAGE))
                    if not rows:
                        raise SegaError("즐겨찾기 페이지를 읽지 못했어요.")
                    result: dict = {"ok": True}
                    if job["type"] == "apply":
                        found, missing = favorites.pick(rows, job.get("songs") or [])
                        found = found[:favorites.LIMIT]
                        await net.post(favorites.SET, [("idx", "99"), *[("music[]", r.value) for r in found]])
                        rows = net_parsers.parse_maimai_favorites(await net.get(favorites.PAGE))
                        checked = {(r.genre, r.title) for r in rows if r.checked}
                        result["missing"] = missing
                        result["failed"] = [r.title for r in found if (r.genre, r.title) not in checked]
                        log.info("favorites applied from the site for %s: %d songs", discord_id, len(checked))
                    result["rows"] = [[r.title, r.genre, r.checked] for r in rows]
                self._keep_token(discord_id, net, token)
        except Exception as e:
            result = {"ok": False, "error": str(e) or type(e).__name__}
            if not isinstance(e, SegaError):
                log.exception("site job %s failed", job.get("id"))
        try:
            await self.client.finish(job["id"], result)
        except SiteError as e:
            log.warning("could not report site job %s: %s", job.get("id"), e)

    def _log_once(self, key: str, template: str, *args) -> None:
        if key not in self._failing:
            self._failing.add(key)
            log.warning(template, *args)


# --------------------------------------------------------------------------- commands and loops


def register(bot: "ChumaiBot") -> None:
    client = SiteClient.from_env()
    bot.site = client
    bot.site_sync = SiteSync(bot, client)
    sync = bot.site_sync
    group = app_commands.Group(name="site", description="maimai 기록 사이트(mai records) 연동")

    @group.command(name="link", description="기록 사이트 계정과 연결합니다 (사이트 설정 → 디스코드 봇 연결에서 코드 받기)")
    @app_commands.describe(code="사이트에서 받은 연결 코드")
    async def site_link(interaction: discord.Interaction, code: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            username = await client.link(interaction.user.id, code)
        except SiteError as e:
            await interaction.followup.send(f"연결하지 못했어요: {e}", ephemeral=True)
            return
        # 이 봇에 저장해 둔 즐겨찾기 프리셋은 사이트로 옮긴다 (이제 사이트 것을 같이 쓰니까)
        moved = 0
        for name, songs in bot.links.presets(interaction.user.id, "maimai"):
            try:
                await client.save_preset(interaction.user.id, name, songs)
                bot.links.delete_preset(interaction.user.id, "maimai", name)
                moved += 1
            except SiteError:
                log.warning("could not move preset %r to the site", name, exc_info=True)
        lines = [f"**{username}** 계정과 연결했어요. {client.profile_url(username)}"]
        if moved:
            lines.append(f"이 봇에 있던 즐겨찾기 프리셋 {moved}개를 사이트로 옮겼어요.")
        if bot.links.get_sega_token(interaction.user.id) is None:
            lines.append("기록을 올리려면 `/login` 으로 SEGA ID 로그인도 해 주세요.")
        else:
            lines.append("1~2분 안에 기록을 올려요. 다음부터는 새 플레이가 있으면 자동으로 올라가고, "
                         "바로 올리려면 `/site sync`.")
            sync.request_upload(interaction.user.id)
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @group.command(name="unlink", description="기록 사이트와 연결을 끊습니다")
    async def site_unlink(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            ok = await client.unlink(interaction.user.id)
        except SiteError as e:
            await interaction.followup.send(f"끊지 못했어요: {e}", ephemeral=True)
            return
        await interaction.followup.send("사이트와 연결을 끊었어요." if ok else "연결된 사이트 계정이 없어요.", ephemeral=True)

    @group.command(name="sync", description="maimai 기록을 지금 기록 사이트에 올립니다")
    async def site_sync(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            username = await client.username(interaction.user.id)
            if username is None:
                raise SiteError("사이트 계정과 연결되지 않았어요. 사이트 설정에서 코드를 받아 `/site link` 해 주세요.")

            async def progress(text: str) -> None:
                try:
                    await interaction.edit_original_response(content=text)
                except discord.HTTPException:
                    pass

            result = await sync.upload(interaction.user.id, progress)
        except (SiteError, SegaError, site_payload.PageError) as e:
            await interaction.edit_original_response(content=f"올리지 못했어요: {e}")
            return
        await interaction.edit_original_response(
            content=f"올렸어요! 기록 {result['charts']}개 · 바뀐 기록 {result.get('changed', 0)}개 · "
                    f"최근 플레이 {result['plays']}곡\n{client.profile_url(username)}")

    tree = bot.tree
    tree.add_command(group)


class SiteLoops:
    """The background work: site jobs every few seconds, new-play checks every minute."""

    def __init__(self, bot: "ChumaiBot"):
        self.bot = bot

    def start(self) -> None:
        if self.bot.site.enabled:
            self.jobs.start()
            self.records.start()
            log.info("site link on: %s", self.bot.site.url)

    def stop(self) -> None:
        self.jobs.cancel()
        self.records.cancel()

    @tasks.loop(seconds=5)
    async def jobs(self) -> None:
        await self.bot.site_sync.run_jobs()

    @tasks.loop(minutes=1)
    async def records(self) -> None:
        await self.bot.site_sync.auto_sync()

    @jobs.before_loop
    async def _ready_jobs(self) -> None:
        await self.bot.wait_until_ready()

    @records.before_loop
    async def _ready_records(self) -> None:
        await self.bot.wait_until_ready()
