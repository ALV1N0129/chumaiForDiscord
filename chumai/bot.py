"""Discord bot: slash commands for maimai DX / CHUNITHM B50."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Literal

import discord
from discord import app_commands
from discord.ext import tasks

from . import answers, charts as charts_module, features, logbuffer, net_parsers, prefix, render, updater
from .b50 import B50, b50_from_chunithm_net, b50_from_maimai_net
from .charts import ChartViews
from .config import Config
from .jackets import JacketStore
from .fonts import ensure_font
from .logos import download_logos
from .playlog import badges as play_badges, to_entry
from .render import render_b50, render_credit
from .segaid import LoginFailed, NetClient, SegaError, forget_sessions, login
from .songdb import SongDB, normalize_title
from .storage import LinkStore

log = logging.getLogger("chumai")

GameChoice = Literal["maimai", "chunithm"]


def _minutes(name: str, default: float) -> float:
    try:
        return max(1.0, float(os.environ.get(name) or default))
    except ValueError:
        return default


# how often each linked play log is checked (one page per check); PLAYLOG_INTERVAL_MINUTES in .env
PLAYLOG_INTERVAL = _minutes("PLAYLOG_INTERVAL_MINUTES", 1) * 60
LIVE_LOG_SETTING = "live_log_channel"
PLAYLOG_PATHS = {"chunithm": "/mobile/record/playlog", "maimai": "/maimai-mobile/record/"}


class ChumaiBot(discord.Client):
    def __init__(self, config: Config):
        intents = discord.Intents.default()
        # reading "!b50" style messages needs the Message Content intent (enable it in the developer portal)
        intents.message_content = bool(config.prefix)
        # no message cache: prefix commands only need the message they came with (saves memory)
        super().__init__(intents=intents, max_messages=None)
        self.config = config
        self.tree = app_commands.CommandTree(self)
        self.links = LinkStore(config.db_path, config.token_key)
        self.songdb = SongDB()
        self.jackets = JacketStore(config.jacket_dir)
        self.charts = ChartViews(config.chart_dir)
        self.b50_cache: dict[tuple[int, str], tuple[float, B50]] = {}  # reused by /recommend and /whatif
        register_commands(self)
        features.register(self)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not self.config.prefix or not message.content.startswith(self.config.prefix):
            return
        await prefix.handle(self, message, self.config.prefix)

    async def setup_hook(self) -> None:
        await self.songdb.load_or_update(self.config.songdb_dir)
        await self.jackets.load_or_update()
        self._charts_task = asyncio.create_task(self._load_charts())  # large download; don't wait
        self._aliases_task = asyncio.create_task(self._load_community_aliases())
        render.release_memory()
        render.LOGO_DIR = Path(self.config.logo_dir)
        await download_logos(self.config.logo_dir, self.config.logo_urls)
        if await ensure_font(render.FONT_DIR):
            render.cjk.cache_clear()
        self.refresh_songdb.start()
        if updater.enabled():
            await updater.remember_start()
            self.check_update.start()
        self.poll_playlogs.start()
        self.push_live_logs.start()
        if self.config.guild_id:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("synced %d commands to server %s: %s", len(synced), self.config.guild_id,
                     ", ".join(c.name for c in synced))
        else:
            synced = await self.tree.sync()
            log.info("synced %d global commands (GUILD_ID not set; may take a while to show up): %s",
                     len(synced), ", ".join(c.name for c in synced))

    restart_requested = False
    owner_ids: set[int] | None = None
    # (discord_id, game) -> (next check time, last time new plays were seen)
    _playlog_schedule: dict[tuple[int, str], tuple[float, float]] = {}
    # (discord_id, game) -> (when it was last checked, how it went), for /logs
    playlog_status: dict[tuple[int, str], tuple[float, str]] = {}

    @tasks.loop(minutes=1)
    async def poll_playlogs(self) -> None:
        now = time.time()
        for discord_id, game, channel_id, last_key in self.links.playlogs():
            due, active = self._playlog_schedule.get((discord_id, game), (0.0, 0.0))
            if now < due:
                continue
            before = self.playlog_status.get((discord_id, game), (0.0, ""))[1]
            try:
                found = await check_playlog(self, discord_id, game, channel_id, last_key)
                self.playlog_status[(discord_id, game)] = (time.time(), "새 크레딧 올림" if found else "정상")
                if before.startswith("실패"):
                    log.info("play log check for %s/%s works again", discord_id, game)
            except Exception as e:
                status = f"실패: {str(e) or type(e).__name__}"
                if status != before:  # once per new failure, not every minute
                    log.exception("play log check failed for %s/%s", discord_id, game)
                self.playlog_status[(discord_id, game)] = (time.time(), status)
                found = False
            if found:
                active = now
            self._playlog_schedule[(discord_id, game)] = (time.time() + PLAYLOG_INTERVAL, active)

    @poll_playlogs.before_loop
    async def _wait_ready(self) -> None:
        await self.wait_until_ready()

    @tasks.loop(seconds=5)
    async def push_live_logs(self) -> None:
        """Send new log lines to the live log channel (/logs live), a few messages at a time."""
        channel_id = self.links.get_setting(LIVE_LOG_SETTING)
        if not channel_id:
            logbuffer.recent.pending.clear()
            return
        channel = self.get_channel(int(channel_id))
        for _ in range(3):
            chunk = logbuffer.recent.take()
            if not chunk:
                break
            if channel is None:
                return
            try:
                await channel.send(f"```\n{chunk}\n```")
            except Exception as e:
                logging.getLogger("chumai.live").warning("could not send logs to channel %s: %s", channel_id, e)
                return

    @push_live_logs.before_loop
    async def _wait_ready_logs(self) -> None:
        await self.wait_until_ready()

    @tasks.loop(minutes=1)
    async def check_update(self) -> None:
        if await updater.pull_if_updated():
            log.info("new version pulled; restarting")
            self.restart_requested = True
            # close() cancels this loop, so it must run in its own task: awaited here, the
            # cancellation would stop it halfway and the old code would keep running
            self._restart_task = asyncio.create_task(self.close())

    @tasks.loop(hours=24)
    async def refresh_songdb(self) -> None:
        await self.songdb.load_or_update(self.config.songdb_dir)
        await self.jackets.load_or_update()
        await self.charts.load_or_update()
        self._load_chart_aliases()
        await self._load_community_aliases()
        render.release_memory()

    async def _load_charts(self) -> None:
        await self.charts.load_or_update()
        self._load_chart_aliases()
        render.release_memory()

    def _load_chart_aliases(self) -> None:
        """chuni-penguin's CHUNITHM nicknames, saved with the chart index (see charts.py)."""
        path = Path(self.config.chart_dir) / charts_module.ALIASES_NAME
        try:
            if path.exists():
                answers.set_community("penguin", "chunithm", json.loads(path.read_text(encoding="utf-8")).items())
        except Exception:
            log.warning("could not load chuni-penguin nicknames", exc_info=True)

    async def _load_community_aliases(self) -> None:
        try:
            await answers.update_community(Path(self.config.songdb_dir).parent / "aliases")
        except Exception:
            log.warning("could not load community nicknames", exc_info=True)

    @refresh_songdb.before_loop
    async def _skip_first_refresh(self) -> None:
        await asyncio.sleep(24 * 60 * 60)

    async def close(self) -> None:
        self.refresh_songdb.cancel()
        self.check_update.cancel()
        self.poll_playlogs.cancel()
        self.push_live_logs.cancel()
        await super().close()


def register_commands(bot: ChumaiBot) -> None:
    tree = bot.tree

    @tree.command(name="login", description="SEGA ID로 로그인해서 CHUNITHM-NET / maimai DX NET 기록을 불러옵니다 (국제판)")
    async def login_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(SegaLoginModal(bot))

    @tree.command(name="logout", description="저장된 SEGA ID 로그인 정보를 삭제합니다")
    async def logout(interaction: discord.Interaction) -> None:
        token = bot.links.get_sega_token(interaction.user.id)
        if token:
            forget_sessions(token)
        removed = bot.links.delete_sega_token(interaction.user.id)
        msg = "로그인 정보를 삭제했어요." if removed else "저장된 로그인 정보가 없어요."
        await interaction.response.send_message(msg, ephemeral=True)

    @tree.command(name="privacy", description="다른 사람이 내 B50(SEGA ID 연동)을 볼 수 있는지 설정합니다")
    @app_commands.describe(public="켜면 다른 사람이 /b50 member:나 로 내 기록을 볼 수 있어요")
    async def privacy(interaction: discord.Interaction, public: bool) -> None:
        if not bot.links.set_public(interaction.user.id, public):
            await interaction.response.send_message("먼저 `/login` 으로 로그인해 주세요.", ephemeral=True)
            return
        msg = "이제 다른 사람도 내 B50을 볼 수 있어요." if public else "이제 나만 내 B50을 볼 수 있어요."
        await interaction.response.send_message(msg, ephemeral=True)

    @tree.command(name="b50", description="maimai DX / CHUNITHM 베스트 50 레이팅표를 보여줍니다")
    @app_commands.describe(
        game="게임",
        member="다른 디스코드 유저의 B50 보기",
    )
    async def b50(
        interaction: discord.Interaction,
        game: GameChoice,
        member: discord.User | None = None,
    ) -> None:
        who = member or interaction.user
        is_self = who.id == interaction.user.id
        token = bot.links.get_sega_token(who.id)
        if token is None:
            hint = "`/login` 으로 먼저 SEGA ID 로그인을 해 주세요." if is_self else f"{who.mention} 님은 로그인하지 않았어요."
            await interaction.response.send_message(hint, ephemeral=True)
            return
        if not is_self and not bot.links.is_public(who.id):
            await interaction.response.send_message(f"{who.mention} 님은 기록을 비공개로 설정했어요.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        result = await sega_b50(bot, game, who.id, token)
        await send_b50(interaction, result, game)

    playlog = app_commands.Group(name="playlog", description="플레이 기록을 이 채널에 자동으로 올립니다")

    @playlog.command(name="on", description="새로 플레이한 크레딧을 이 채널에 자동으로 올리기 시작합니다")
    @app_commands.describe(game="게임")
    async def playlog_on(interaction: discord.Interaction, game: GameChoice) -> None:
        token = bot.links.get_sega_token(interaction.user.id)
        if token is None:
            await interaction.response.send_message("`/login` 으로 먼저 SEGA ID 로그인을 해 주세요.", ephemeral=True)
            return
        missing = missing_permissions(interaction.channel)
        if missing:
            await interaction.response.send_message(permission_message(missing), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with NetClient(game, token) as net:
                records = parse_playlog(game, await net.get(PLAYLOG_PATHS[game]))
                last_key = max((r.key for r in records), default="")
                # best scores now, so the next new records can show how much they improved
                await seed_bests(bot, net, interaction.user.id, game, last_key)
        except SegaError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        bot.links.set_playlog(interaction.user.id, game, interaction.channel_id, last_key)
        bot._playlog_schedule.pop((interaction.user.id, game), None)
        await interaction.followup.send(
            f"이제 {'maimai DX' if game == 'maimai' else 'CHUNITHM'} 플레이 기록을 이 채널에 올릴게요. "
            f"크레딧이 끝나고 공식 사이트에 반영된 뒤 {PLAYLOG_INTERVAL / 60:g}분 안에 올라와요.",
            ephemeral=True,
        )

    @playlog.command(name="off", description="플레이 기록 자동 업로드를 끕니다")
    @app_commands.describe(game="게임")
    async def playlog_off(interaction: discord.Interaction, game: GameChoice) -> None:
        removed = bot.links.delete_playlog(interaction.user.id, game)
        await interaction.response.send_message("껐어요." if removed else "켜져 있지 않아요.", ephemeral=True)

    @playlog.command(name="test", description="최근 크레딧 하나를 이 채널에 바로 올려 봅니다 (자동 업로드 설정은 그대로)")
    @app_commands.describe(game="게임")
    async def playlog_test(interaction: discord.Interaction, game: GameChoice) -> None:
        token = bot.links.get_sega_token(interaction.user.id)
        if token is None:
            await interaction.response.send_message("`/login` 으로 먼저 SEGA ID 로그인을 해 주세요.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with NetClient(game, token) as net:
                records = parse_playlog(game, await net.get(PLAYLOG_PATHS[game]))
            credits = net_parsers.group_credits(records)
            if not credits:
                await interaction.followup.send("최근 플레이 기록이 없어요.", ephemeral=True)
                return
            # pretend everything up to the credit before the last one was already posted
            before = credits[-2][-1].key if len(credits) > 1 else ""
            await check_playlog(bot, interaction.user.id, game, interaction.channel_id, before, update=False)
        except SegaError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send(
                permission_message(missing_permissions(interaction.channel) or ["메시지 보내기", "파일 첨부"]),
                ephemeral=True)
            return
        except Exception:
            log.exception("play log test failed")
            await interaction.followup.send("테스트 중 오류가 났어요. 봇 창의 로그를 확인해 주세요.", ephemeral=True)
            return
        await interaction.followup.send("최근 크레딧을 올렸어요.", ephemeral=True)

    tree.add_command(playlog)

    async def owner_only(interaction: discord.Interaction) -> bool:
        """For owner commands, after deferring: True for the bot's owner, else says so."""
        if bot.owner_ids is None:
            app = await bot.application_info()
            bot.owner_ids = {m.id for m in app.team.members} if app.team else {app.owner.id}
        if interaction.user.id not in bot.owner_ids:
            await interaction.followup.send("봇 주인만 쓸 수 있어요.", ephemeral=True)
            return False
        return True

    logs = app_commands.Group(name="logs", description="봇 로그와 플레이 로그 확인 상태 (봇 주인만)")

    @logs.command(name="status", description="플레이 로그 확인 상태와 최근 로그를 봅니다 (봇 주인만)")
    async def logs_status(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await owner_only(interaction):
            return
        subs = bot.links.playlogs()
        live = bot.links.get_setting(LIVE_LOG_SETTING)
        lines = [f"**플레이 로그 자동 업로드** ({len(subs)}개, {PLAYLOG_INTERVAL / 60:g}분마다 · "
                 f"체커 {'동작 중' if bot.poll_playlogs.is_running() else '**멈춤**'})"]
        for discord_id, game, _, _ in subs:
            when, how = bot.playlog_status.get((discord_id, game), (0.0, "아직 확인 전"))
            at = f"<t:{int(when)}:R>" if when else "-"
            lines.append(f"· <@{discord_id}> {game}: {how} ({at})")
        lines.append(f"실시간 로그: {f'<#{live}>' if live else '꺼짐 (`/logs live on`)'}")
        recent = logbuffer.recent.tail(15)
        text = "\n".join(lines)
        body = "\n".join(recent) if recent else "없음"
        room = 1900 - len(text)
        while len(body) > room and "\n" in body:
            body = body.split("\n", 1)[1]  # keep the newest lines
        await interaction.followup.send(f"{text}\n**최근 로그**\n```\n{body[-room:]}\n```", ephemeral=True)

    @logs.command(name="live", description="이 채널에 봇 로그를 실시간으로 올립니다 / 끕니다 (봇 주인만)")
    @app_commands.describe(switch="on: 이 채널에 올리기 / off: 끄기")
    async def logs_live(interaction: discord.Interaction, switch: Literal["on", "off"]) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await owner_only(interaction):
            return
        if switch == "off":
            bot.links.set_setting(LIVE_LOG_SETTING, None)
            await interaction.followup.send("실시간 로그를 껐어요.", ephemeral=True)
            return
        missing = missing_permissions(interaction.channel)
        if missing:
            await interaction.followup.send(permission_message(missing), ephemeral=True)
            return
        bot.links.set_setting(LIVE_LOG_SETTING, str(interaction.channel_id))
        logbuffer.recent.pending.clear()
        await interaction.followup.send(
            "이제 이 채널에 봇 로그를 실시간으로 올릴게요 (경고·오류, 시작·업데이트, 크레딧 업로드). "
            "채널에 있는 사람은 모두 볼 수 있으니 비공개 채널을 추천해요.", ephemeral=True)
        log.info("live logs on in channel %s", interaction.channel_id)

    tree.add_command(logs)

    @tree.command(name="update", description="GitHub에서 최신 코드를 바로 받아서 봇을 재시작합니다 (봇 주인만)")
    async def update_cmd(interaction: discord.Interaction) -> None:
        # answer Discord first (it gives up after 3 seconds), then do the slow parts
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await owner_only(interaction):
            return
        if not updater.enabled():
            await interaction.followup.send("git으로 받은 폴더가 아니라서 업데이트할 수 없어요.", ephemeral=True)
            return
        try:
            pulled, message = await updater.check()
        except Exception as e:
            log.exception("update failed")
            await interaction.followup.send(f"업데이트에 실패했어요: {e}", ephemeral=True)
            return
        await interaction.followup.send(message, ephemeral=True)
        if not pulled:
            return
        bot.restart_requested = True
        await bot.close()

    @tree.command(name="calc", description="보면 상수와 점수로 단일 곡 레이팅을 계산합니다")
    @app_commands.describe(
        game="게임",
        const="보면 상수 (예: 14.7)",
        score="maimai: 달성률 (예: 100.5) / CHUNITHM: 점수 (예: 1007500)",
    )
    async def calc(interaction: discord.Interaction, game: GameChoice, const: float, score: float) -> None:
        await interaction.response.defer(thinking=True)
        png = await asyncio.to_thread(features.calc_image, game, const, score)
        await interaction.followup.send(file=discord.File(io.BytesIO(png), filename=render.filename(f"calc_{game}")))


class SegaLoginModal(discord.ui.Modal, title="SEGA ID 로그인 (국제판)"):
    sega_id = discord.ui.TextInput(label="SEGA ID", min_length=1, max_length=100)
    password = discord.ui.TextInput(label="비밀번호", min_length=1, max_length=100)
    otp = discord.ui.TextInput(
        label="2단계 인증 코드 (사용 중일 때만)", required=False, min_length=6, max_length=6
    )

    def __init__(self, bot: ChumaiBot):
        super().__init__(timeout=300)
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            clal = await login(self.sega_id.value, self.password.value, self.otp.value or None)
        except LoginFailed as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except Exception:
            log.exception("SEGA ID login failed")
            await interaction.followup.send("SEGA 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.", ephemeral=True)
            return
        self.bot.links.set_sega_token(interaction.user.id, clal)
        await interaction.followup.send(
            "로그인 완료. 비밀번호는 저장하지 않으며, `/logout` 으로 로그인 정보를 지울 수 있어요.",
            ephemeral=True,
        )


async def _fetch_image(net: NetClient, url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        return await net.get_bytes(url)
    except Exception:
        log.warning("could not load profile image %s", url, exc_info=True)
        return None


B50_CACHE_SECONDS = 180


async def sega_b50(bot: ChumaiBot, game: str, discord_id: int, token: str, images: bool = True) -> B50 | str:
    """Fetch the B50 from the official site.

    images=False skips the profile icon and nameplate (not needed by /recommend and /whatif) and
    may reuse a B50 fetched in the last few minutes. Pages are loaded in parallel.
    """
    key = (discord_id, game)
    cached = bot.b50_cache.get(key)
    if not images and cached and time.time() - cached[0] < B50_CACHE_SECONDS:
        return cached[1]
    try:
        async with NetClient(game, token) as net:
            if game == "chunithm":
                # the first page also logs in; the rest can then load together
                player = net_parsers.parse_chunithm_player(await net.get("/mobile/home/playerData/"))
                paths = ["/mobile/home/playerData/ratingDetailBest/", "/mobile/home/playerData/ratingDetailRecent/"]
                pages = await asyncio.gather(*(net.get(p) for p in paths))
                best, new = (net_parsers.parse_chunithm_rating_list(p) for p in pages)
                if images:
                    await _chunithm_lamps(net, best + new)
                    try:
                        player.plate_url = net_parsers.parse_chunithm_nameplate(
                            await net.get("/mobile/collection/customise/")
                        )
                    except Exception:
                        log.warning("could not load CHUNITHM nameplate", exc_info=True)
                result = b50_from_chunithm_net(player, best, new, bot.songdb)
                if not images:  # /recommend and /whatif: only suggest charts the region has
                    result.available = await _chunithm_available(net)
            else:
                player = net_parsers.parse_maimai_player(await net.get("/maimai-mobile/home/"))
                pages = await asyncio.gather(*(
                    net.get(f"/maimai-mobile/record/musicGenre/search/?genre=99&diff={diff}") for diff in range(5)
                ))
                seen = {d: set() for base in net_parsers.MAIMAI_DIFFS for d in (base, f"DX {base}")}
                records = [r for diff, html in enumerate(pages)
                           for r in net_parsers.parse_maimai_scores(html, diff, seen)]
                result = b50_from_maimai_net(player, records, bot.songdb, bot.config.new_versions[game])
                result.played = {(r.title, r.difficulty): r.achievement for r in records}  # for /recommend
                # every song on the record pages, played or not
                result.available = {d: {normalize_title(t) for t in titles} for d, titles in seen.items()}
            if images:
                result.icon, result.plate = await asyncio.gather(
                    _fetch_image(net, player.icon_url), _fetch_image(net, player.plate_url))
        if net.clal != token:
            bot.links.set_sega_token(discord_id, net.clal)
        bot.b50_cache[key] = (time.time(), result)
        return result
    except SegaError as e:
        return str(e)
    except Exception:
        log.exception("failed to fetch %s data from SEGA NET", game)
        return "공식 사이트에서 데이터를 가져오지 못했어요. 점검 중이거나 사이트 구조가 바뀌었을 수 있어요."


def parse_playlog(game: str, html: bytes):
    if game == "chunithm":
        return net_parsers.parse_chunithm_playlog(html)
    return net_parsers.parse_maimai_playlog(html)


async def _cached_image(bot: ChumaiBot, net: NetClient, game: str, url: str | None) -> str | None:
    if not url:
        return None
    name = url.split("?")[0].rsplit("/", 1)[-1]
    path = Path(bot.config.jacket_dir) / game / name
    if not path.exists():
        data = await _fetch_image(net, url)
        if data is None:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return str(path)


CHUNITHM_RECORD_DIFFS = ["BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA"]


async def _chunithm_lamps(net: NetClient, records: list) -> None:
    """Fill in AJC/AJ/FC from the record pages of the difficulties in `records` (the rating lists
    don't show them). One page at a time: each lists every song."""
    try:
        for diff in [d for d in CHUNITHM_RECORD_DIFFS if any(r.difficulty == d for r in records)]:
            html = await net.post(f"/mobile/record/musicGenre/send{diff.capitalize()}", {"genre": "99"})
            lamps = net_parsers.parse_chunithm_lamps(html)
            del html
            for r in records:
                if r.difficulty == diff:
                    r.lamp = lamps.get(r.idx)
    except Exception:
        log.warning("could not load CHUNITHM lamps", exc_info=True)


# the difficulties /recommend suggests; their record pages list every song the region has
CHUNITHM_AVAILABLE_DIFFS = ["EXPERT", "MASTER", "ULTIMA"]


async def _chunithm_available(net: NetClient) -> dict[str, set] | None:
    """{difficulty: music ids} of the charts in the player's region (None if the pages failed), so
    songs not out yet on the international version aren't suggested. One page at a time."""
    try:
        out = {}
        for diff in CHUNITHM_AVAILABLE_DIFFS:
            html = await net.post(f"/mobile/record/musicGenre/send{diff.capitalize()}", {"genre": "99"})
            out[diff] = net_parsers.parse_chunithm_music_ids(html)
            del html
        return out
    except Exception:
        log.warning("could not load the CHUNITHM song list", exc_info=True)
        return None


async def fetch_bests(net: NetClient, game: str, diffs: set[str] | None = None) -> dict[tuple[str, str], float]:
    """Best score per (title, difficulty) from the record pages, for `diffs` (all if None)."""
    out: dict[tuple[str, str], float] = {}
    if game == "chunithm":
        try:
            wanted = [d for d in CHUNITHM_RECORD_DIFFS if diffs is None or d in diffs]
            pages = await asyncio.gather(*(
                net.post(f"/mobile/record/musicGenre/send{d.capitalize()}", {"genre": "99"}) for d in wanted))
            for html in pages:
                out.update({(r.title, r.difficulty): r.score for r in net_parsers.parse_chunithm_rating_list(html)})
        except SegaError:
            # fall back to the B50 lists (only the 50 rated charts, but the same pages /b50 uses)
            log.warning("CHUNITHM record pages failed; using the rating lists", exc_info=True)
            for path in ("/mobile/home/playerData/ratingDetailBest/", "/mobile/home/playerData/ratingDetailRecent/"):
                out.update({(r.title, r.difficulty): r.score
                            for r in net_parsers.parse_chunithm_rating_list(await net.get(path))})
    else:
        wanted = [i for i, base in enumerate(net_parsers.MAIMAI_DIFFS)
                  if diffs is None or base in diffs or f"DX {base}" in diffs]
        pages = await asyncio.gather(*(
            net.get(f"/maimai-mobile/record/musicGenre/search/?genre=99&diff={i}") for i in wanted))
        for i, html in zip(wanted, pages):
            out.update({(r.title, r.difficulty): r.achievement for r in net_parsers.parse_maimai_scores(html, i)})
    return out


async def seed_bests(bot: ChumaiBot, net: NetClient, discord_id: int, game: str, play_key: str) -> None:
    try:
        bot.links.save_bests(discord_id, game, await fetch_bests(net, game), play_key)
    except Exception:
        log.warning("could not load best scores", exc_info=True)


async def render_credits(bot: ChumaiBot, discord_id: int, game: str, select,
                         save_bests: bool = False) -> tuple[list[bytes], list]:
    """Fetch the play log and render the credits of the records chosen by `select(records)`.

    Each play gets a badge: NEW (+improvement), TIE or BEST <score>. The improvement comes from
    the best scores saved last time; `save_bests` stores the current ones for next time.
    """
    token = bot.links.get_sega_token(discord_id)
    if token is None:
        raise SegaError("`/login` 으로 먼저 SEGA ID 로그인을 해 주세요.")
    async with NetClient(game, token) as net:
        records = parse_playlog(game, await net.get(PLAYLOG_PATHS[game]))
        chosen = select(records)
        if not chosen:
            return [], []
        if game == "chunithm":
            player = net_parsers.parse_chunithm_player(await net.get("/mobile/home/playerData/"))
        else:
            player = net_parsers.parse_maimai_player(await net.get("/maimai-mobile/home/"))
        icon = await _fetch_image(net, player.icon_url)

        cache, cache_key = bot.links.get_bests(discord_id, game)
        latest = max(r.key for r in records)
        diffs = None if cache_key is None else {r.difficulty for r in records if r.key > cache_key}
        try:
            now = await fetch_bests(net, game, diffs) if diffs != set() else {}
        except Exception:
            log.warning("could not load best scores", exc_info=True)
            now = None
        marks = play_badges(chosen, cache, cache_key, now or {}, bot.songdb, bot.config.new_versions[game], game)
        if now is not None and (save_bests or cache_key is None):
            bot.links.save_bests(discord_id, game, now, latest)
        rating_before = bot.links.get_rating(discord_id, game)
        if player.rating and (save_bests or rating_before is None):
            bot.links.save_rating(discord_id, game, player.rating)

        images = []
        credits = net_parsers.group_credits(chosen)
        for n, credit in enumerate(credits):
            entries = [to_entry(game, r, bot.songdb, bot.jackets.unrated_level) for r in credit]
            paths = await asyncio.gather(*(_cached_image(bot, net, game, r.jacket_url) for r in credit))
            for e, path in zip(entries, paths):
                e.jacket_path = path
            # the site only shows the rating now, so the change goes on the newest credit
            before = rating_before if n == len(credits) - 1 else None
            png = await asyncio.to_thread(
                render_credit, game, player.name, entries, [marks.get(r.key) for r in credit], credit[0].date, icon,
                player.rating, before,
            )
            images.append(png)
    if net.clal != token:
        bot.links.set_sega_token(discord_id, net.clal)
    return images, chosen


def latest_credit(records):
    credits = net_parsers.group_credits(records)
    return credits[-1] if credits else []


async def check_playlog(
    bot: ChumaiBot, discord_id: int, game: str, channel_id: int, last_key: str, update: bool = True
) -> bool:
    """Post credits played since last_key. Returns True if there were new plays."""
    if bot.links.get_sega_token(discord_id) is None:
        return False
    images, new = await render_credits(bot, discord_id, game, lambda rs: [r for r in rs if r.key > last_key],
                                       save_bests=update)
    if not new:
        return False
    if update:
        bot.links.update_playlog_key(discord_id, game, max(r.key for r in new))
    channel = bot.get_channel(channel_id)
    if channel is not None:
        try:
            for i, png in enumerate(images):
                await channel.send(file=discord.File(io.BytesIO(png), filename=render.filename(f"playlog_{game}_{i}")))
            log.info("posted %d credit(s) for %s/%s", len(images), discord_id, game)
        except discord.Forbidden:
            if not update:
                raise
            log.warning("no permission to post play logs in channel %s (%s)", channel_id,
                        ", ".join(missing_permissions(channel)) or "unknown")
    return True


PERMISSION_NAMES = {"view_channel": "채널 보기", "send_messages": "메시지 보내기", "attach_files": "파일 첨부"}


def missing_permissions(channel) -> list[str]:
    """Permissions the bot lacks to post play log images in `channel` (empty if fine or unknown)."""
    guild = getattr(channel, "guild", None)
    if guild is None or not hasattr(channel, "permissions_for"):
        return []
    perms = channel.permissions_for(guild.me)
    if isinstance(channel, discord.Thread):
        needed = {"view_channel": perms.view_channel, "send_messages": perms.send_messages_in_threads,
                  "attach_files": perms.attach_files}
    else:
        needed = {k: getattr(perms, k) for k in PERMISSION_NAMES}
    return [PERMISSION_NAMES[k] for k, ok in needed.items() if not ok]


def permission_message(missing: list[str]) -> str:
    return (f"봇이 이 채널에 글을 올릴 권한이 없어요: **{', '.join(missing)}**\n"
            "채널 설정 → 권한 에서 봇(또는 봇 역할)에 이 권한을 허용하거나, 봇이 글을 쓸 수 있는 채널에서 다시 해 주세요.")


async def attach_jackets(bot: ChumaiBot, result: B50) -> None:
    entries = result.old + result.new
    try:
        paths = await bot.jackets.fetch(result.game, [e.song_key for e in entries])
    except Exception:
        log.exception("failed to fetch jackets")
        return
    for i, path in paths.items():
        entries[i].jacket_path = str(path)


async def send_b50(interaction: discord.Interaction, result: B50 | str, game: str) -> None:
    if isinstance(result, str):
        await interaction.followup.send(result)
        return
    if not result.old and not result.new:
        await interaction.followup.send(f"**{result.username}** 의 {game} 기록이 없어요.")
        return

    await attach_jackets(interaction.client, result)
    png = await asyncio.to_thread(render_b50, result)
    await interaction.followup.send(file=discord.File(io.BytesIO(png), filename=render.filename(f"b50_{game}")))


def main() -> None:
    render.tune_malloc()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger().addHandler(logbuffer.recent)  # for /logs
    config = Config.from_env()
    bot = ChumaiBot(config)
    try:
        bot.run(config.discord_token, log_handler=None)
    except discord.PrivilegedIntentsRequired:
        log.error(
            "접두어 명령어를 쓰려면 Discord 개발자 포털 → Bot → 'Message Content Intent'를 켜 주세요. "
            "접두어 명령어를 안 쓰려면 .env에 PREFIX= 를 빈 값으로 넣으세요."
        )
        raise SystemExit(1)
    finally:
        # closed only after everything else has stopped, so commands still running during a
        # restart can finish their database writes
        bot.links.close()
    if bot.restart_requested:
        raise SystemExit(updater.RESTART_EXIT_CODE)
