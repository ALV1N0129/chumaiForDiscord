"""Discord bot: slash commands for maimai DX / CHUNITHM B50."""

from __future__ import annotations

import asyncio
import io
import logging
import re
from typing import Literal

import discord
from discord import app_commands

from . import rating
from .b50 import build_b50
from .config import Config
from .render import render_b50
from .storage import LinkStore
from .tachi import TachiClient, TachiError, UserNotFound

log = logging.getLogger("chumai")

GameChoice = Literal["maimai", "chunithm"]
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
PROFILE_URL = "https://kamai.tachi.ac/u/{user}"


class ChumaiBot(discord.Client):
    def __init__(self, config: Config):
        super().__init__(intents=discord.Intents.default())
        self.config = config
        self.tree = app_commands.CommandTree(self)
        self.tachi = TachiClient(config.tachi_base_url, config.tachi_api_key)
        self.links = LinkStore(config.db_path)
        register_commands(self)

    async def setup_hook(self) -> None:
        if self.config.guild_id:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def close(self) -> None:
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

    @tree.command(name="b50", description="maimai DX / CHUNITHM 베스트 50 레이팅표를 보여줍니다")
    @app_commands.describe(
        game="게임",
        member="다른 디스코드 유저의 B50 보기 (연동되어 있어야 함)",
        username="Kamaitachi 유저 이름으로 직접 조회",
    )
    async def b50(
        interaction: discord.Interaction,
        game: GameChoice,
        member: discord.User | None = None,
        username: str | None = None,
    ) -> None:
        if username:
            if not USERNAME_RE.match(username):
                await interaction.response.send_message("올바르지 않은 유저 이름입니다.", ephemeral=True)
                return
            target = username
        else:
            who = member or interaction.user
            target = bot.links.get(who.id)
            if target is None:
                hint = "`/link` 로 먼저 Kamaitachi 계정을 연동해 주세요." if who == interaction.user else (
                    f"{who.mention} 님은 연동된 계정이 없어요."
                )
                await interaction.response.send_message(hint, ephemeral=True)
                return

        await interaction.response.defer(thinking=True)
        try:
            bundle = await bot.tachi.fetch_all_pbs(target, game)
        except UserNotFound:
            await interaction.followup.send(f"Kamaitachi 유저 **{target}** 을(를) 찾을 수 없어요.")
            return
        except TachiError as e:
            await interaction.followup.send(f"Kamaitachi에서 데이터를 가져오지 못했어요: {e}")
            return
        except Exception:
            log.exception("failed to fetch PBs for %s", target)
            await interaction.followup.send("Kamaitachi 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.")
            return

        result = build_b50(game, bundle, bot.config.new_versions[game])
        if not result.old and not result.new:
            await interaction.followup.send(f"**{target}** 의 {game} 기록이 없어요.")
            return

        png = await asyncio.to_thread(render_b50, result)
        file = discord.File(io.BytesIO(png), filename=f"b50_{game}_{target}.png")
        embed = discord.Embed(
            title=f"{target} · {'maimai DX' if game == 'maimai' else 'CHUNITHM'} B50",
            url=PROFILE_URL.format(user=target),
            description=f"레이팅 **{result.total_text()}**",
            color=0xF5C542 if game == "maimai" else 0xE0457B,
        )
        embed.set_image(url=f"attachment://{file.filename}")
        embed.set_footer(text="데이터: Kamaitachi")
        await interaction.followup.send(embed=embed, file=file)

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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config.from_env()
    bot = ChumaiBot(config)
    bot.run(config.discord_token, log_handler=None)
