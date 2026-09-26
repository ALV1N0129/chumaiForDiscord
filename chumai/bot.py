"""Discord bot: slash commands for maimai DX / CHUNITHM B50."""

from __future__ import annotations

import asyncio
import io
import logging
import re
from typing import Literal

import discord
from discord import app_commands

from discord.ext import tasks

from . import net_parsers, rating
from .b50 import B50, b50_from_chunithm_net, b50_from_maimai_net, build_b50
from .config import Config
from .render import render_b50
from .segaid import LoginFailed, NetClient, SegaError, login
from .songdb import SongDB
from .storage import LinkStore
from .tachi import TachiClient, TachiError, UserNotFound

log = logging.getLogger("chumai")

GameChoice = Literal["maimai", "chunithm"]
SourceChoice = Literal["auto", "sega", "kamaitachi"]
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
PROFILE_URL = "https://kamai.tachi.ac/u/{user}"


class ChumaiBot(discord.Client):
    def __init__(self, config: Config):
        super().__init__(intents=discord.Intents.default())
        self.config = config
        self.tree = app_commands.CommandTree(self)
        self.tachi = TachiClient(config.tachi_base_url, config.tachi_api_key)
        self.links = LinkStore(config.db_path, config.token_key)
        self.songdb = SongDB()
        register_commands(self)

    async def setup_hook(self) -> None:
        await self.songdb.load_or_update(self.config.songdb_dir)
        self.refresh_songdb.start()
        if self.config.guild_id:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    @tasks.loop(hours=24)
    async def refresh_songdb(self) -> None:
        await self.songdb.load_or_update(self.config.songdb_dir)

    @refresh_songdb.before_loop
    async def _skip_first_refresh(self) -> None:
        await asyncio.sleep(24 * 60 * 60)

    async def close(self) -> None:
        self.refresh_songdb.cancel()
        await self.tachi.close()
        self.links.close()
        await super().close()


def register_commands(bot: ChumaiBot) -> None:
    tree = bot.tree

    @tree.command(name="link", description="내 디스코드 계정에 Kamaitachi 아이디를 연동합니다")
    @app_commands.describe(username="Kamaitachi(kamai.tachi.ac) 유저 이름")
    async def link(interaction: discord.Interaction, username: str) -> None:
        if not USERNAME_RE.match(username):
            await interaction.response.send_message("올바르지 않은 유저 이름입니다.", ephemeral=True)
            return
        bot.links.set(interaction.user.id, username)
        await interaction.response.send_message(
            f"✅ Kamaitachi 계정 **{username}** 을(를) 연동했어요.\n{PROFILE_URL.format(user=username)}",
            ephemeral=True,
        )

    @tree.command(name="unlink", description="Kamaitachi 연동을 해제합니다")
    async def unlink(interaction: discord.Interaction) -> None:
        removed = bot.links.delete(interaction.user.id)
        msg = "연동을 해제했어요." if removed else "연동된 계정이 없어요."
        await interaction.response.send_message(msg, ephemeral=True)

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
        username="Kamaitachi 유저 이름으로 직접 조회",
        source="데이터 출처 (기본: SEGA ID 로그인이 있으면 공식 사이트, 없으면 Kamaitachi)",
    )
    async def b50(
        interaction: discord.Interaction,
        game: GameChoice,
        member: discord.User | None = None,
        username: str | None = None,
        source: SourceChoice = "auto",
    ) -> None:
        if username:
            if not USERNAME_RE.match(username):
                await interaction.response.send_message("올바르지 않은 유저 이름입니다.", ephemeral=True)
                return
            await interaction.response.defer(thinking=True)
            await send_b50(interaction, await kamaitachi_b50(bot, game, username), game)
            return

        who = member or interaction.user
        is_self = who.id == interaction.user.id
        token = bot.links.get_sega_token(who.id) if source in ("auto", "sega") else None
        if token and not is_self and not bot.links.is_public(who.id):
            token = None
            if source == "sega":
                await interaction.response.send_message(f"{who.mention} 님은 기록을 비공개로 설정했어요.", ephemeral=True)
                return
        tachi_user = bot.links.get(who.id) if source in ("auto", "kamaitachi") else None

        if token is None and tachi_user is None:
            if source == "sega":
                hint = "`/login` 으로 먼저 SEGA ID 로그인을 해 주세요." if is_self else f"{who.mention} 님은 SEGA ID 로그인을 하지 않았어요."
            else:
                hint = "`/login`(SEGA ID) 또는 `/link`(Kamaitachi)로 먼저 계정을 연결해 주세요." if is_self else (
                    f"{who.mention} 님은 연결된 계정이 없어요."
                )
            await interaction.response.send_message(hint, ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        if token is not None:
            result = await sega_b50(bot, game, who.id, token)
        else:
            result = await kamaitachi_b50(bot, game, tachi_user)
        await send_b50(interaction, result, game)

    @tree.command(name="calc", description="보면 상수와 점수로 단일 곡 레이팅을 계산합니다")
    @app_commands.describe(
        game="게임",
        const="보면 상수 (예: 14.7)",
        score="maimai: 달성률 (예: 100.5) / CHUNITHM: 점수 (예: 1007500)",
    )
    async def calc(interaction: discord.Interaction, game: GameChoice, const: float, score: float) -> None:
        if game == "maimai":
            value = rating.maimai_rating(const, score)
            text = f"{const:.1f} · {score:.4f}% ({rating.maimai_rank(score)}) → **{value}**"
        else:
            value = rating.chunithm_rating(const, int(score))
            text = f"{const:.1f} · {int(score):,} ({rating.chunithm_rank(int(score))}) → **{float(value):.2f}**"
        await interaction.response.send_message(text)


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
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return
        except Exception:
            log.exception("SEGA ID login failed")
            await interaction.followup.send("❌ SEGA 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.", ephemeral=True)
            return
        self.bot.links.set_sega_token(interaction.user.id, clal)
        await interaction.followup.send(
            "✅ 로그인했어요! 이제 `/b50` 으로 공식 사이트 기록을 볼 수 있어요.\n"
            "비밀번호는 저장하지 않고, 로그인 유지용 토큰만 저장해요. `/logout` 으로 언제든 삭제할 수 있어요.",
            ephemeral=True,
        )


async def kamaitachi_b50(bot: ChumaiBot, game: str, username: str) -> B50 | str:
    try:
        bundle = await bot.tachi.fetch_all_pbs(username, game)
    except UserNotFound:
        return f"Kamaitachi 유저 **{username}** 을(를) 찾을 수 없어요."
    except TachiError as e:
        return f"Kamaitachi에서 데이터를 가져오지 못했어요: {e}"
    except Exception:
        log.exception("failed to fetch PBs for %s", username)
        return "Kamaitachi 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요."
    return build_b50(game, bundle, bot.config.new_versions[game])


async def sega_b50(bot: ChumaiBot, game: str, discord_id: int, token: str) -> B50 | str:
    try:
        async with NetClient(game, token) as net:
            if game == "chunithm":
                player = net_parsers.parse_chunithm_player(await net.get("/mobile/home/playerData/"))
                best = net_parsers.parse_chunithm_rating_list(
                    await net.get("/mobile/home/playerData/ratingDetailBest/")
                )
                new = net_parsers.parse_chunithm_rating_list(
                    await net.get("/mobile/home/playerData/ratingDetailRecent/")
                )
                result = b50_from_chunithm_net(player, best, new, bot.songdb)
            else:
                player = net_parsers.parse_maimai_player(await net.get("/maimai-mobile/home/"))
                records = []
                for diff in range(5):
                    html = await net.get(f"/maimai-mobile/record/musicGenre/search/?genre=99&diff={diff}")
                    records += net_parsers.parse_maimai_scores(html, diff)
                result = b50_from_maimai_net(player, records, bot.songdb, bot.config.new_versions[game])
        if net.clal != token:
            bot.links.set_sega_token(discord_id, net.clal)
        return result
    except SegaError as e:
        return str(e)
    except Exception:
        log.exception("failed to fetch %s data from SEGA NET", game)
        return "공식 사이트에서 데이터를 가져오지 못했어요. 점검 중이거나 사이트 구조가 바뀌었을 수 있어요."


async def send_b50(interaction: discord.Interaction, result: B50 | str, game: str) -> None:
    if isinstance(result, str):
        await interaction.followup.send(result)
        return
    if not result.old and not result.new:
        await interaction.followup.send(f"**{result.username}** 의 {game} 기록이 없어요.")
        return

    png = await asyncio.to_thread(render_b50, result)
    file = discord.File(io.BytesIO(png), filename=f"b50_{game}.png")
    rating_text = result.official_rating or result.total_text()
    embed = discord.Embed(
        title=f"{result.username} · {'maimai DX' if game == 'maimai' else 'CHUNITHM'} B50",
        description=f"레이팅 **{rating_text}**",
        color=0xF5C542 if game == "maimai" else 0xE0457B,
    )
    if result.source == "Kamaitachi":
        embed.url = PROFILE_URL.format(user=result.username)
    embed.set_image(url=f"attachment://{file.filename}")
    embed.set_footer(text=f"데이터: {result.source}")
    await interaction.followup.send(embed=embed, file=file)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config.from_env()
    bot = ChumaiBot(config)
    bot.run(config.discord_token, log_handler=None)
