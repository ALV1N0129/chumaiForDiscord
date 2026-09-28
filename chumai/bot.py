"""Discord bot: slash commands for maimai DX / CHUNITHM B50."""

from __future__ import annotations

import asyncio
import io
import logging
import time
from pathlib import Path
from typing import Literal

import discord
from discord import app_commands
from discord.ext import tasks

from . import features, net_parsers, prefix, render, updater
from .b50 import B50, b50_from_chunithm_net, b50_from_maimai_net
from .charts import ChartViews
from .config import Config
from .jackets import JacketStore
from .fonts import ensure_font
from .logos import download_logos
from .playlog import badges as play_badges, to_entry
from .render import render_b50, render_credit
from .segaid import LoginFailed, NetClient, SegaError, login
from .songdb import SongDB
from .storage import LinkStore

log = logging.getLogger("chumai")

GameChoice = Literal["maimai", "chunithm"]
PLAYLOG_ACTIVE_INTERVAL = 5 * 60
PLAYLOG_IDLE_INTERVAL = 15 * 60
PLAYLOG_PATHS = {"chunithm": "/mobile/record/playlog", "maimai": "/maimai-mobile/record/"}


class ChumaiBot(discord.Client):
    def __init__(self, config: Config):
        intents = discord.Intents.default()
        # reading "!b50" style messages needs the Message Content intent (enable it in the developer portal)
        intents.message_content = bool(config.prefix)
        super().__init__(intents=intents)
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
        self._charts_task = asyncio.create_task(self.charts.load_or_update())  # large download; don't wait
        render.LOGO_DIR = Path(self.config.logo_dir)
        await download_logos(self.config.logo_dir, self.config.logo_urls)
        if await ensure_font(render.FONT_DIR):
            render.cjk.cache_clear()
        self.refresh_songdb.start()
        if updater.enabled():
            self.check_update.start()
        self.poll_playlogs.start()
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

    @tasks.loop(minutes=1)
    async def poll_playlogs(self) -> None:
        now = time.time()
        for discord_id, game, channel_id, last_key in self.links.playlogs():
            due, active = self._playlog_schedule.get((discord_id, game), (0.0, 0.0))
            if now < due:
                continue
            try:
                found = await check_playlog(self, discord_id, game, channel_id, last_key)
            except Exception:
                log.exception("play log check failed for %s/%s", discord_id, game)
                found = False
            if found:
                active = now
            # 5 minutes for an hour after activity, otherwise 15 minutes
            interval = PLAYLOG_ACTIVE_INTERVAL if now - active < 3600 else PLAYLOG_IDLE_INTERVAL
            self._playlog_schedule[(discord_id, game)] = (time.time() + interval, active)

    @poll_playlogs.before_loop
    async def _wait_ready(self) -> None:
        await self.wait_until_ready()

    @tasks.loop(minutes=1)
    async def check_update(self) -> None:
        if await updater.pull_if_updated():
            log.info("new version pulled; restarting")
            self.restart_requested = True
            await self.close()

    @tasks.loop(hours=24)
    async def refresh_songdb(self) -> None:
        await self.songdb.load_or_update(self.config.songdb_dir)
        await self.jackets.load_or_update()
        await self.charts.load_or_update()

    @refresh_songdb.before_loop
    async def _skip_first_refresh(self) -> None:
        await asyncio.sleep(24 * 60 * 60)

    async def close(self) -> None:
        self.refresh_songdb.cancel()
        self.check_update.cancel()
        self.poll_playlogs.cancel()
        await super().close()


def register_commands(bot: ChumaiBot) -> None:
    tree = bot.tree

    @tree.command(name="login", description="SEGA ID로 로그인해서 CHUNITHM-NET / maimai DX NET 기록을 불러옵니다 (국제판)")
    async def login_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(SegaLoginModal(bot))

    @tree.command(name="logout", description="저장된 SEGA ID 로그인 정보를 삭제합니다")
    async def logout(interaction: discord.Interaction) -> None:
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
            "크레딧이 끝나고 공식 사이트에 반영된 뒤 5~15분 안에 올라와요.",
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
        except Exception:
            log.exception("play log test failed")
            await interaction.followup.send("테스트 중 오류가 났어요. 봇 창의 로그를 확인해 주세요.", ephemeral=True)
            return
        await interaction.followup.send("최근 크레딧을 올렸어요.", ephemeral=True)

    tree.add_command(playlog)

    @tree.command(name="update", description="GitHub에서 최신 코드를 바로 받아서 봇을 재시작합니다 (봇 주인만)")
    async def update_cmd(interaction: discord.Interaction) -> None:
        # answer Discord first (it gives up after 3 seconds), then do the slow parts
        await interaction.response.defer(ephemeral=True, thinking=True)
        if bot.owner_ids is None:
            app = await bot.application_info()
            bot.owner_ids = {m.id for m in app.team.members} if app.team else {app.owner.id}
        if interaction.user.id not in bot.owner_ids:
            await interaction.followup.send("봇 주인만 쓸 수 있어요.", ephemeral=True)
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
                    try:
                        player.plate_url = net_parsers.parse_chunithm_nameplate(
                            await net.get("/mobile/collection/customise/")
                        )
                    except Exception:
                        log.warning("could not load CHUNITHM nameplate", exc_info=True)
                result = b50_from_chunithm_net(player, best, new, bot.songdb)
            else:
                player = net_parsers.parse_maimai_player(await net.get("/maimai-mobile/home/"))
                pages = await asyncio.gather(*(
                    net.get(f"/maimai-mobile/record/musicGenre/search/?genre=99&diff={diff}") for diff in range(5)
                ))
                records = [r for diff, html in enumerate(pages) for r in net_parsers.parse_maimai_scores(html, diff)]
                result = b50_from_maimai_net(player, records, bot.songdb, bot.config.new_versions[game])
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
        marks = play_badges(chosen, cache, cache_key, now or {})
        if now is not None and (save_bests or cache_key is None):
            bot.links.save_bests(discord_id, game, now, latest)

        images = []
        for credit in net_parsers.group_credits(chosen):
            entries = [to_entry(game, r, bot.songdb) for r in credit]
            paths = await asyncio.gather(*(_cached_image(bot, net, game, r.jacket_url) for r in credit))
            for e, path in zip(entries, paths):
                e.jacket_path = path
            png = await asyncio.to_thread(
                render_credit, game, player.name, entries, [marks.get(r.key) for r in credit], credit[0].date, icon,
                player.rating,
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
        for i, png in enumerate(images):
            await channel.send(file=discord.File(io.BytesIO(png), filename=render.filename(f"playlog_{game}_{i}")))
    return True


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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
