"""Discord bot: slash commands for maimai DX / CHUNITHM B50."""

from __future__ import annotations

import asyncio
import datetime
import io
import json
import logging
import sys
import os
import shutil
import time
from pathlib import Path
from typing import Literal

import discord
from discord import app_commands
from discord.ext import tasks

from . import answers, features, i18n, logbuffer, net_parsers, prefix, render, updater
from .b50 import B50, b50_from_chunithm_net, b50_from_maimai_net
from .charts import PenguinNicknames
from .config import Config
from .jackets import JacketStore
from .fonts import ensure_font
from .logos import download_logos
from .playlog import badges as play_badges, day_timeline, to_entry
from .render import render_b50, render_credit
from .segaid import LoginFailed, NetClient, SegaError, forget_sessions, login
from .songdb import SongDB, normalize_title
from .storage import PLAYLOG_NEW, PLAYLOG_OFF, PLAYLOG_SKIP, LinkStore

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
PLAYLOG_ALL_SETTING = "playlog_all_channel"  # /playlog all: everyone logged in, posted here
RESTART_NOTICE = "🔄 업데이트를 위해 봇이 재부팅됩니다. (약 1분 소요)"
RESTART_STATUS = "업데이트 중 · 약 1분 뒤에 돌아와요"
AUTO_PLAYLOG_TRIES = 3  # first checks that may fail before a game is left out (e.g. never played)
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
        self.charts = PenguinNicknames(config.chart_dir)
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
        # GCM-bot nicknames were once cached here; the maimai ones now come from assets/nicknames_ko.tsv
        shutil.rmtree(Path(self.config.songdb_dir).parent / "aliases", ignore_errors=True)
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
        await self.tree.set_translator(i18n.KoreanNames())
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

    _auto_tries: dict[tuple[int, str], int] = {}

    @tasks.loop(minutes=1)
    async def poll_playlogs(self) -> None:
        now = time.time()
        everyone = self.links.get_setting(PLAYLOG_ALL_SETTING)
        if everyone:  # whoever logged in since
            self.links.add_auto_playlogs(int(everyone), tuple(PLAYLOG_PATHS))
        for discord_id, game, channel_id, last_key in self.links.playlogs():
            due, active = self._playlog_schedule.get((discord_id, game), (0.0, 0.0))
            if now < due:
                continue
            if everyone:  # all of it goes to that channel, whatever each set
                channel_id = int(everyone)
            if last_key == PLAYLOG_NEW:
                await self._start_auto_playlog(discord_id, game, channel_id)
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

    async def _start_auto_playlog(self, discord_id: int, game: str, channel_id: int) -> None:
        """First check of a /playlog all play log: note where the log is, so only later plays are
        posted. A game that keeps failing (never played?) is left out."""
        key = (discord_id, game)
        self._playlog_schedule[key] = (time.time() + PLAYLOG_INTERVAL, 0.0)
        token = self.links.get_sega_token(discord_id)
        if token is None:
            return
        try:
            async with NetClient(game, token) as net:
                last_key = await start_playlog(self, net, discord_id, game)
            if net.clal != token:
                self.links.set_sega_token(discord_id, net.clal)
        except Exception as e:
            tries = self._auto_tries.get(key, 0) + 1
            self._auto_tries[key] = tries
            self.playlog_status[key] = (time.time(), f"시작 실패: {str(e) or type(e).__name__}")
            if tries >= AUTO_PLAYLOG_TRIES:
                self.links.set_playlog(discord_id, game, channel_id, PLAYLOG_SKIP, auto=True)
                self._auto_tries.pop(key, None)
                log.warning("auto play log for %s/%s left out after %d failed tries", discord_id, game, tries)
            return
        self._auto_tries.pop(key, None)
        self.links.set_playlog(discord_id, game, channel_id, last_key, auto=True)
        self.playlog_status[key] = (time.time(), "정상")
        log.info("auto play log started for %s/%s", discord_id, game)

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
                # plain lines, so <@user> and <#channel> show as names; nobody is pinged
                await channel.send(chunk, allowed_mentions=discord.AllowedMentions.none())
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
            self._restart_task = asyncio.create_task(self._restart())

    async def _restart(self) -> None:
        await self.announce_restart()
        await self.close()

    async def announce_restart(self) -> None:
        """Say the bot is about to restart for an update: in the live log channel, and as the bot's
        status. Never holds up the restart for long."""
        async def announce() -> None:
            try:
                await self.change_presence(activity=discord.Game(RESTART_STATUS))
            except Exception:
                pass
            channel_id = self.links.get_setting(LIVE_LOG_SETTING)
            channel = self.get_channel(int(channel_id)) if channel_id else None
            if channel is not None:
                await channel.send(RESTART_NOTICE)

        try:
            await asyncio.wait_for(announce(), 5)
        except Exception as e:
            logging.getLogger("chumai.live").warning("could not send logs to channel %s: %s", "-", e)

    @tasks.loop(hours=24)
    async def refresh_songdb(self) -> None:
        await self.songdb.load_or_update(self.config.songdb_dir)
        await self.jackets.load_or_update()
        await self.charts.load_or_update()
        self._load_chart_aliases()
        render.release_memory()

    async def _load_charts(self) -> None:
        await self.charts.load_or_update()
        self._load_chart_aliases()
        render.release_memory()

    def _load_chart_aliases(self) -> None:
        """chuni-penguin's CHUNITHM nicknames (see charts.py)."""
        path = self.charts.path
        try:
            if path.exists():
                answers.set_community("penguin", "chunithm", json.loads(path.read_text(encoding="utf-8")).items())
        except Exception:
            log.warning("could not load chuni-penguin nicknames", exc_info=True)

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

    async def _everyone_note(interaction: discord.Interaction) -> bool:
        """While /playlog all is on, each person's own setting doesn't count: says so."""
        everyone = bot.links.get_setting(PLAYLOG_ALL_SETTING)
        if not everyone:
            return False
        await interaction.response.send_message(
            f"지금은 봇 주인이 켠 전체 업로드로, 로그인한 사람 모두의 기록이 <#{everyone}> 에 올라가요. "
            "따로 켜거나 끌 수 없어요.", ephemeral=True)
        return True

    @playlog.command(name="on", description="새로 플레이한 크레딧을 이 채널에 자동으로 올리기 시작합니다")
    @app_commands.describe(game="게임")
    async def playlog_on(interaction: discord.Interaction, game: GameChoice) -> None:
        if await _everyone_note(interaction):
            return
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
                last_key = await start_playlog(bot, net, interaction.user.id, game)
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
        if await _everyone_note(interaction):
            return
        on = any(d == interaction.user.id and g == game for d, g, _, _ in bot.links.playlogs())
        # kept as turned off, so /playlog all doesn't add it back
        bot.links.set_playlog(interaction.user.id, game, 0, PLAYLOG_OFF, auto=True)
        await interaction.response.send_message("껐어요." if on else "켜져 있지 않아요.", ephemeral=True)

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

    @playlog.command(name="all", description="로그인한 사람 모두의 플레이 기록을 이 채널에 올립니다 / 끕니다 (봇 주인만)")
    @app_commands.describe(switch="on: 이 채널에 올리기 / off: 끄기")
    async def playlog_all(interaction: discord.Interaction, switch: Literal["on", "off"]) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await owner_only(interaction):
            return
        if switch == "off":
            bot.links.set_setting(PLAYLOG_ALL_SETTING, None)
            bot.links.delete_auto_playlogs()
            log.info("play log for everyone off")
            await interaction.followup.send(
                "전체 업로드를 껐어요. 각자 `/playlog on` 으로 켠 건 그대로예요.", ephemeral=True)
            return
        missing = missing_permissions(interaction.channel)
        if missing:
            await interaction.followup.send(permission_message(missing), ephemeral=True)
            return
        bot.links.set_setting(PLAYLOG_ALL_SETTING, str(interaction.channel_id))
        bot.links.add_auto_playlogs(interaction.channel_id, tuple(PLAYLOG_PATHS))
        log.info("play log for everyone on in channel %s", interaction.channel_id)
        await interaction.followup.send(
            f"로그인한 {len(bot.links.sega_users())}명의 maimai·CHUNITHM 플레이 기록을 모두 이 채널에 올릴게요. "
            "지금부터 친 것만 올라가고, 안 하는 게임은 몇 번 확인해 보고 알아서 빼요. "
            "켜져 있는 동안은 각자 `/playlog on` 으로 정한 채널 대신 이 채널로 올라가고, 따로 끌 수 없어요.",
            ephemeral=True)

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
        everyone = bot.links.get_setting(PLAYLOG_ALL_SETTING)
        lines = [f"**플레이 로그 자동 업로드** ({len(subs)}개, {PLAYLOG_INTERVAL / 60:g}분마다 · "
                 f"체커 {'동작 중' if bot.poll_playlogs.is_running() else '**멈춤**'})",
                 f"전체 업로드: {f'<#{everyone}>' if everyone else '꺼짐 (`/playlog all on`)'}"]
        for discord_id, game, _, last_key in subs:
            when, how = bot.playlog_status.get((discord_id, game), (0.0, "아직 확인 전"))
            if last_key == PLAYLOG_NEW and not when:
                how = "시작 대기"
            at = f"<t:{int(when)}:R>" if when else "-"
            auto = " (전체)" if bot.links.is_auto_playlog(discord_id, game) else ""
            lines.append(f"· <@{discord_id}> {game}{auto}: {how} ({at})")
        lines.append(f"실시간 로그: {f'<#{live}>' if live else '꺼짐 (`/logs live on`)'}")
        recent = logbuffer.recent.tail(15)
        text = "\n".join(lines)
        body = "\n".join(recent) if recent else "없음"
        room = 1900 - len(text)
        while len(body) > room and "\n" in body:
            body = body.split("\n", 1)[1]  # keep the newest lines
        await interaction.followup.send(f"{text}\n**최근 로그**\n{body[-room:]}", ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

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
            "이제 이 채널에 봇 로그를 한국어로 요약해서 실시간으로 올릴게요 (재부팅·업데이트, 오류, 크레딧 업로드). "
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
        await bot.announce_restart()
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
        head = "로그인 완료. 비밀번호는 저장하지 않으며, `/logout` 으로 로그인 정보를 지울 수 있어요."
        progress = LoginProgress(head)
        progress.message = await interaction.followup.send(progress.text(), ephemeral=True, wait=True)
        self.bot._seed_task = asyncio.create_task(save_all_bests(self.bot, interaction.user.id, progress))


class LoginProgress:
    """The progress bar under the login message while the best scores are fetched."""

    def __init__(self, head: str):
        self.head = head
        self.total = sum(1 + BEST_PAGES[g] for g in PLAYLOG_PATHS)  # each game's play log + record pages
        self.done = 0
        self.label = "준비 중"
        self.started = time.time()
        self.message = None
        self._shown = 0.0

    def text(self) -> str:
        filled = round(10 * self.done / self.total)
        return (f"{self.head}\n`{'▰' * filled}{'▱' * (10 - filled)}` {self.done}/{self.total} · "
                f"{self.label} 받는 중…")

    async def __call__(self, label: str) -> None:
        self.done = min(self.total, self.done + 1)
        self.label = label
        if time.time() - self._shown >= 1.5:  # at most one edit every 1.5s
            await self._show(self.text())

    async def skip(self, steps: int, label: str) -> None:
        """A game that couldn't be read: its steps are done."""
        self.done = min(self.total, self.done + steps - 1)
        await self(label)

    async def finish(self, summary: str) -> None:
        await self._show(f"{self.head}\n✅ 저장 완료 ({time.time() - self.started:.0f}초) · {summary}")

    async def _show(self, content: str) -> None:
        self._shown = time.time()
        if self.message is not None:
            try:
                await self.message.edit(content=content)
            except Exception:
                pass  # the message may be gone; the saving goes on


async def save_all_bests(bot: ChumaiBot, discord_id: int, progress: LoginProgress | None = None) -> None:
    """Right after /login: every game's best scores and where the play log is now, so new
    records from then on show how much they improved (like a score tracker's first sync). A game
    never played just fails. While /playlog all is on, this is also its first check."""
    everyone = bot.links.get_setting(PLAYLOG_ALL_SETTING)
    saved, summary = [], []
    for game in PLAYLOG_PATHS:  # one game at a time: each is several full record pages
        name = "CHUNITHM" if game == "chunithm" else "maimai"
        token = bot.links.get_sega_token(discord_id)
        if token is None:
            return
        steps = progress.done if progress else 0
        try:
            async with NetClient(game, token) as net:
                last_key = await start_playlog(bot, net, discord_id, game, progress)
            if net.clal != token:
                bot.links.set_sega_token(discord_id, net.clal)
        except Exception:
            if progress is not None:
                await progress.skip(1 + BEST_PAGES[game] - (progress.done - steps), f"{name} (기록 없음)")
            summary.append(f"{name} 기록 없음")
            continue
        saved.append(game)
        summary.append(f"{name} {len(bot.links.get_bests(discord_id, game)[0]):,}개 보면")
        if progress is not None:  # all of this game's steps, however many pages it took
            progress.done = max(progress.done, steps + 1 + BEST_PAGES[game])
        if everyone:
            bot.links.add_auto_playlogs(int(everyone), (game,))
            if bot.links.is_auto_playlog(discord_id, game):
                bot.links.set_playlog(discord_id, game, int(everyone), last_key, auto=True)
            else:  # their own play log: only where it is
                bot.links.update_playlog_key(discord_id, game, last_key)
            bot.playlog_status[(discord_id, game)] = (time.time(), "정상")
    render.release_memory()
    if progress is not None:
        await progress.finish(" · ".join(summary))
    if saved:
        log.info("best scores saved for %s: %s", discord_id, ", ".join(saved))


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
                # each page lists every song of a difficulty (MBs): one at a time, read and dropped
                seen = {d: set() for base in net_parsers.MAIMAI_DIFFS for d in (base, f"DX {base}")}
                records = []
                for diff in range(5):
                    html = await net.get(f"/maimai-mobile/record/musicGenre/search/?genre=99&diff={diff}")
                    records += net_parsers.parse_maimai_scores(html, diff, seen)
                    del html
                result = b50_from_maimai_net(player, records, bot.songdb, bot.config.new_versions[game])
                result.played = {(r.title, r.difficulty): r.achievement for r in records}  # for /recommend
                # every song on the record pages, played or not
                # a title is in several difficulties' lists: one string for all of them (3MB -> <1MB)
                result.available = {d: {sys.intern(normalize_title(t)) for t in titles} for d, titles in seen.items()}
            if images:
                result.icon, result.plate = await asyncio.gather(
                    _fetch_image(net, player.icon_url), _fetch_image(net, player.plate_url))
        if net.clal != token:
            bot.links.set_sega_token(discord_id, net.clal)
        if result.official_rating:
            bot.links.log_rating(discord_id, game, result.official_rating)
        now = time.time()
        # only reused for a few minutes; each holds a player's scores and song lists (MBs for maimai)
        for k in [k for k, (at, _) in bot.b50_cache.items() if now - at >= B50_CACHE_SECONDS]:
            del bot.b50_cache[k]
        bot.b50_cache[key] = (now, result)
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


async def fetch_bests(net: NetClient, game: str, diffs: set[str] | None = None,
                      progress=None) -> dict[tuple[str, str], float]:
    """Best score per (title, difficulty) from the record pages, for `diffs` (all if None),
    WORLD'S END and 宴 too. `progress(label)` is awaited after each page."""
    out: dict[tuple[str, str], float] = {}

    async def done(label: str) -> None:
        if progress is not None:
            await progress(label)

    if game == "chunithm":
        try:
            wanted = [d for d in CHUNITHM_RECORD_DIFFS if diffs is None or d in diffs]
            # one page at a time: each lists every song, and holding them all at once ran a small host
            # out of memory
            for d in wanted:
                html = await net.post(f"/mobile/record/musicGenre/send{d.capitalize()}", {"genre": "99"})
                out.update({(r.title, r.difficulty): r.score for r in net_parsers.parse_chunithm_record_scores(html)})
                del html
                await done(f"CHUNITHM {d}")
            if diffs is None or "WORLD'S END" in diffs:
                try:  # extra: without it the others still count
                    html = await net.get("/mobile/record/worldsEndList")
                    out.update({(r.title, r.difficulty): r.score
                                for r in net_parsers.parse_chunithm_record_scores(html)})
                    del html
                except Exception:
                    log.warning("could not load the %s record page", "WORLD'S END", exc_info=True)
                await done("CHUNITHM WORLD'S END")
        except SegaError:
            # fall back to the B50 lists (only the 50 rated charts, but the same pages /b50 uses)
            log.warning("CHUNITHM record pages failed; using the rating lists", exc_info=True)
            for path in ("/mobile/home/playerData/ratingDetailBest/", "/mobile/home/playerData/ratingDetailRecent/"):
                out.update({(r.title, r.difficulty): r.score
                            for r in net_parsers.parse_chunithm_rating_list(await net.get(path))})
    else:
        wanted = [i for i, base in enumerate(net_parsers.MAIMAI_DIFFS)
                  if diffs is None or base in diffs or f"DX {base}" in diffs]
        if diffs is None or "UTAGE" in diffs:
            wanted.append(net_parsers.MAIMAI_UTAGE)
        for i in wanted:  # one page at a time: each lists every song of a difficulty
            try:
                html = await net.get(f"/maimai-mobile/record/musicGenre/search/?genre=99&diff={i}")
            except Exception:
                if i != net_parsers.MAIMAI_UTAGE:
                    raise
                log.warning("could not load the %s record page", "UTAGE", exc_info=True)  # extra, as above
                await done("maimai UTAGE")
                continue
            out.update({(r.title, r.difficulty): r.achievement for r in net_parsers.parse_maimai_scores(html, i)})
            del html
            await done(f"maimai {net_parsers.maimai_diff_name(i)}")
    return out


BEST_PAGES = {"chunithm": len(CHUNITHM_RECORD_DIFFS) + 1, "maimai": len(net_parsers.MAIMAI_DIFFS) + 1}


async def start_playlog(bot: ChumaiBot, net: NetClient, discord_id: int, game: str, progress=None) -> str:
    """Where a play log starts: the newest play now (only later ones get posted), with the best
    scores as of then, so the next new records can show how much they improved."""
    records = parse_playlog(game, await net.get(PLAYLOG_PATHS[game]))
    if progress is not None:
        await progress(f"{'CHUNITHM' if game == 'chunithm' else 'maimai'} 플레이 기록")
    last_key = max((r.key for r in records), default="")
    await seed_bests(bot, net, discord_id, game, last_key, progress)
    return last_key


async def seed_bests(bot: ChumaiBot, net: NetClient, discord_id: int, game: str, play_key: str,
                     progress=None) -> None:
    try:
        bot.links.save_bests(discord_id, game, await fetch_bests(net, game, progress=progress), play_key)
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
        if player.rating:
            bot.links.log_rating(discord_id, game, player.rating)

        cache, cache_key = bot.links.get_bests(discord_id, game)
        latest = max(r.key for r in records)
        diffs = None if cache_key is None else {r.difficulty for r in records if r.key > cache_key}
        try:
            now = await fetch_bests(net, game, diffs) if diffs != set() else {}
        except Exception:
            log.warning("could not load best scores", exc_info=True)
            now = None
        marks = play_badges(chosen, cache, cache_key, now or {}, bot.songdb, bot.config.new_versions[game], game)
        if save_bests:  # for /today: the best scores move on, so how these compared is kept
            bot.links.save_marks(discord_id, game, marks)
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


JST = datetime.timezone(datetime.timedelta(hours=9))
DAY_STARTS = datetime.timedelta(hours=4)  # plays until 4am count for the day before


def play_time(record) -> datetime.datetime:
    return datetime.datetime.strptime(record.date, "%Y/%m/%d %H:%M").replace(tzinfo=JST)


def play_day(record) -> datetime.date:
    return (play_time(record) - DAY_STARTS).date()


def today(now: datetime.datetime | None = None) -> datetime.date:
    """The day /today shows: in Japan time, until 4am still the day before, as for plays."""
    return ((now or datetime.datetime.now(JST)).astimezone(JST) - DAY_STARTS).date()


async def render_today(bot: ChumaiBot, discord_id: int, game: str) -> bytes | None:
    """Today's play (/today): credits, tracks, new records and lamps, the rating from
    before the day's first play to now as a graph stepping up at each new record, and a column per
    credit with its charts. None if nothing was played today. The official site keeps the
    last 50 plays, so a long day may be cut short."""
    token = bot.links.get_sega_token(discord_id)
    if token is None:
        raise SegaError("`/login` 으로 먼저 SEGA ID 로그인을 해 주세요.")
    async with NetClient(game, token) as net:
        records = parse_playlog(game, await net.get(PLAYLOG_PATHS[game]))
        day = today()
        plays = sorted((r for r in records if play_day(r) == day), key=lambda r: r.key)
        if not plays:
            return None
        if game == "chunithm":
            player = net_parsers.parse_chunithm_player(await net.get("/mobile/home/playerData/"))
        else:
            player = net_parsers.parse_maimai_player(await net.get("/maimai-mobile/home/"))
        icon = await _fetch_image(net, player.icon_url)
        start = play_time(plays[0]).timestamp()
        before = bot.links.rating_at(discord_id, game, start)
        if player.rating:
            bot.links.log_rating(discord_id, game, player.rating)

        cache, cache_key = bot.links.get_bests(discord_id, game)
        diffs = None if cache_key is None else {r.difficulty for r in plays if r.key > cache_key}
        try:
            now = await fetch_bests(net, game, diffs) if diffs != set() else {}
        except Exception:
            log.warning("could not load best scores", exc_info=True)
            now = {}
        marks = play_badges(plays, cache, cache_key, now, bot.songdb, bot.config.new_versions[game], game)
        # plays already posted: as they compared then (the saved best scores have moved on since)
        marks.update({k: b for k, b in bot.links.get_marks(discord_id, game).items()
                      if cache_key is not None and k <= cache_key})

        timeline, steps = day_timeline(plays, marks)
        top, full = (("AJ", {"AJ", "AJC"}), ("FC", {"FC"})) if game == "chunithm" else \
            (("AP", {"AP", "AP+"}), ("FC", {"FC", "FC+"}))
        stats = [("크레딧", str(len(timeline))), ("플레이", str(len(plays))),
                 ("신기록", str(len({(r.title, r.difficulty) for r in plays if r.new_record}))),
                 (top[0], str(len({(r.title, r.difficulty) for r in plays if r.lamp in top[1]}))),
                 (full[0], str(len({(r.title, r.difficulty) for r in plays if r.lamp in full[1]})))]
        # the graph ends at the rating now; without it, starts at the one logged before the day
        gained = sum(g for _, _, g, _ in steps)
        try:
            start = float(player.rating) - gained if player.rating else float(before)
        except (TypeError, ValueError):
            start = None
        urls = list({slot.play.jacket_url for _, credit in timeline for slot in credit if slot.play.jacket_url})
        jackets = dict(zip(urls, await asyncio.gather(*(_cached_image(bot, net, game, u) for u in urls))))
        credits = []
        for time, credit in timeline:
            slots = []
            for slot in credit:
                e = to_entry(game, slot.play, bot.songdb, bot.jackets.unrated_level)
                e.jacket_path = jackets.get(slot.play.jacket_url)
                slots.append(render.DaySlot(e, slot.new, slot.count, slot.gain, slot.delta, slot.first))
            credits.append(render.DayCredit(time, slots))
        png = await asyncio.to_thread(
            render.render_day, game, player.name, day.strftime("%Y/%m/%d"), stats, credits, steps, start, icon,
            player.rating, before)
    if net.clal != token:
        bot.links.set_sega_token(discord_id, net.clal)
    return png


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
