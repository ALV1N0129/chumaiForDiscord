"""Extra commands: profile, recent, song info/jacket, const lists, random, reach, what-if, recommend,
the jacket guessing game and help."""

from __future__ import annotations

import asyncio
import io
import logging
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from PIL import Image

from . import net_parsers, tools
from .b50 import B50
from .segaid import NetClient, SegaError
from .songdb import CatalogSong, normalize_title, search

if TYPE_CHECKING:
    from .bot import ChumaiBot

log = logging.getLogger(__name__)

GameChoice = Literal["maimai", "chunithm"]
GAME_NAMES = {"maimai": "maimai DX", "chunithm": "CHUNITHM"}
COLORS = {"maimai": 0xF5C542, "chunithm": 0xE0457B}


DIFF_COLORS = {
    "basic": 0x22BB5B, "advanced": 0xFE8C00, "expert": 0xFE0048, "master": 0x8A2BE2,
    "ultima": 0x131313, "re:master": 0xDCADFF,
}
DIFF_NAMES = {
    "basic": "BASIC", "advanced": "ADVANCED", "expert": "EXPERT", "master": "MASTER",
    "ultima": "ULTIMA", "re:master": "Re:MASTER",
}


def chart_embed(game: str, song: CatalogSong, chart) -> discord.Embed:
    """One chart as a card: title, artist, genre and difficulty/level (constant)."""
    d = chart.difficulty.lower()
    is_dx = d.startswith("dx ")
    key = d[3:] if is_dx else d
    name = ("DX " if is_dx else "") + DIFF_NAMES.get(key, chart.difficulty)
    embed = discord.Embed(title=song.title, description=song.artist or None, color=DIFF_COLORS.get(key, COLORS[game]))
    embed.add_field(name="Category", value=song.genre or "-")
    embed.add_field(name=name, value=f"{chart.level} ({chart.level_const:.1f})")
    return embed


def _song_line(game: str, song: CatalogSong, chart) -> str:
    return f"**{song.title}** — {tools.short(chart.difficulty)} {chart.level} ({chart.level_const:.1f})"


async def _jacket_file(bot: ChumaiBot, song: CatalogSong, name: str = "jacket.png") -> discord.File | None:
    try:
        paths = await bot.jackets.fetch(song.game, [song.jacket_key])
    except Exception:
        log.warning("jacket fetch failed", exc_info=True)
        return None
    path = paths.get(0)
    return discord.File(str(path), filename=name) if path else None


async def song_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    bot: ChumaiBot = interaction.client  # type: ignore[assignment]
    game = getattr(interaction.namespace, "game", None) or "chunithm"
    if not current:
        return []
    return [app_commands.Choice(name=s.title[:100], value=s.title[:100]) for s in search(bot.songdb, game, current, 20)]


def _find_song(bot: ChumaiBot, game: str, query: str) -> CatalogSong | None:
    found = search(bot.songdb, game, query, 1)
    return found[0] if found else None


# ------------------------------------------------------------------ guessing game


@dataclass
class GuessRound:
    game: str
    song: CatalogSong
    jacket: str
    started: float = field(default_factory=time.time)
    answered: bool = False


def _answer_matches(song: CatalogSong, answer: str) -> bool:
    import difflib

    a = normalize_title(answer)
    if not a:
        return False
    return any(a == k or difflib.SequenceMatcher(None, a, k).ratio() >= 0.85 for k in song.keys)


def _crop_hint(path: str, rng: random.Random) -> bytes:
    with Image.open(path) as im:
        im = im.convert("RGB")
    size = int(min(im.size) * 0.35)
    x = rng.randint(0, im.width - size)
    y = rng.randint(0, im.height - size)
    hint = im.crop((x, y, x + size, y + size)).resize((300, 300), Image.LANCZOS)
    buf = io.BytesIO()
    hint.save(buf, "PNG")
    return buf.getvalue()


GUESS_SECONDS = 60


def register(bot: ChumaiBot) -> None:
    tree = bot.tree
    rounds: dict[int, GuessRound] = {}

    # ---------------------------------------------------------------- profile / recent

    @tree.command(name="profile", description="공식 사이트 프로필 카드를 보여줍니다")
    @app_commands.describe(game="게임", member="다른 디스코드 유저 (공개 설정인 경우)")
    async def profile(interaction: discord.Interaction, game: GameChoice, member: discord.User | None = None) -> None:
        from .bot import _fetch_image
        from .render import render_profile

        who = member or interaction.user
        token = bot.links.get_sega_token(who.id)
        if token is None or (who.id != interaction.user.id and not bot.links.is_public(who.id)):
            await interaction.response.send_message("로그인하지 않았거나 비공개로 설정된 계정이에요.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            async with NetClient(game, token) as net:
                if game == "chunithm":
                    player = net_parsers.parse_chunithm_player(await net.get("/mobile/home/playerData/"))
                    try:
                        player.plate_url = net_parsers.parse_chunithm_nameplate(
                            await net.get("/mobile/collection/customise/"))
                    except Exception:
                        log.warning("nameplate failed", exc_info=True)
                else:
                    player = net_parsers.parse_maimai_player(await net.get("/maimai-mobile/home/"))
                icon = await _fetch_image(net, player.icon_url)
                plate = await _fetch_image(net, player.plate_url)
        except SegaError as e:
            await interaction.followup.send(str(e))
            return
        png = await asyncio.to_thread(render_profile, game, player.name, player.rating, player.title,
                                      player.title_rarity, player.level, icon, plate)
        await interaction.followup.send(file=discord.File(io.BytesIO(png), filename=f"profile_{game}.png"))

    @tree.command(name="recent", description="가장 최근 크레딧의 플레이 기록을 보여줍니다")
    @app_commands.describe(game="게임")
    async def recent(interaction: discord.Interaction, game: GameChoice) -> None:
        from .bot import latest_credit, render_credits

        await interaction.response.defer(thinking=True)
        try:
            images, chosen = await render_credits(bot, interaction.user.id, game, latest_credit)
        except SegaError as e:
            await interaction.followup.send(str(e))
            return
        if not images:
            await interaction.followup.send("최근 플레이 기록이 없어요.")
            return
        await interaction.followup.send(file=discord.File(io.BytesIO(images[-1]), filename=f"recent_{game}.png"))

    # ------------------------------------------------------------------ song info

    @tree.command(name="info", description="곡 정보를 검색합니다 (난이도별 상수, 버전, 자켓)")
    @app_commands.describe(game="게임", song="곡 제목 (일부만 입력해도 돼요)")
    @app_commands.autocomplete(song=song_autocomplete)
    async def info(interaction: discord.Interaction, game: GameChoice, song: str) -> None:
        found = _find_song(bot, game, song)
        if found is None:
            await interaction.response.send_message("곡을 찾지 못했어요.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        lines = []
        for c in tools.sort_charts(found.charts):
            const = f"{c.level_const:.1f}" if c.level_const else "-"
            lines.append(f"`{tools.short(c.difficulty):<10}` {c.level:<4} ({const})")
        versions = sorted({c.display_version for c in found.charts if c.display_version})
        embed = discord.Embed(title=found.title, description=found.artist, color=COLORS[game])
        embed.add_field(name="보면", value="\n".join(lines)[:1024] or "-", inline=False)
        if found.genre:
            embed.add_field(name="장르", value=found.genre)
        if versions:
            embed.add_field(name="버전", value=", ".join(versions)[:1024])
        file = await _jacket_file(bot, found)
        if file:
            embed.set_thumbnail(url=f"attachment://{file.filename}")
            await interaction.followup.send(embed=embed, file=file)
        else:
            await interaction.followup.send(embed=embed)

    @tree.command(name="jacket", description="곡 자켓 이미지를 보여줍니다")
    @app_commands.describe(game="게임", song="곡 제목")
    @app_commands.autocomplete(song=song_autocomplete)
    async def jacket(interaction: discord.Interaction, game: GameChoice, song: str) -> None:
        found = _find_song(bot, game, song)
        if found is None:
            await interaction.response.send_message("곡을 찾지 못했어요.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        file = await _jacket_file(bot, found)
        if file is None:
            await interaction.followup.send(f"**{found.title}** 의 자켓을 찾지 못했어요.")
            return
        await interaction.followup.send(content=f"**{found.title}**", file=file)

    # ------------------------------------------------------------ const / random

    @tree.command(name="const", description="레벨·상수·범위에 해당하는 보면 목록")
    @app_commands.describe(game="게임", level=tools.LEVEL_HELP)
    async def const(interaction: discord.Interaction, game: GameChoice, level: str) -> None:
        try:
            lo, hi = tools.parse_level(level, game)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        charts = tools.charts_in_range(bot.songdb, game, lo, hi)
        if not charts:
            await interaction.response.send_message("해당하는 보면이 없어요.", ephemeral=True)
            return
        lines = [_song_line(game, s, c) for s, c in charts]
        body, shown = "", 0
        for line in lines:
            if len(body) + len(line) + 1 > 3900:
                break
            body += line + "\n"
            shown += 1
        if shown < len(lines):
            body += f"… 외 {len(lines) - shown}개"
        embed = discord.Embed(title=f"{GAME_NAMES[game]} {tools.describe_level(level, lo, hi)} ({len(lines)}개)",
                              description=body, color=COLORS[game])
        await interaction.response.send_message(embed=embed)

    @tree.command(name="random", description="레벨·상수·범위에서 랜덤으로 곡을 골라 줍니다 (접두어: !r)")
    @app_commands.describe(game="게임", level=tools.LEVEL_HELP, count="곡 수 (1~4, 기본 3)")
    async def random_cmd(interaction: discord.Interaction, game: GameChoice, level: str,
                         count: app_commands.Range[int, 1, 4] = 3) -> None:
        try:
            lo, hi = tools.parse_level(level, game)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        picks = tools.random_charts(bot.songdb, game, lo, hi, count)
        if not picks:
            await interaction.response.send_message("해당하는 보면이 없어요.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            jackets = await bot.jackets.fetch(game, [s.jacket_key for s, _ in picks])
        except Exception:
            log.warning("jacket fetch failed", exc_info=True)
            jackets = {}
        embeds, files = [], []
        for i, (song, chart) in enumerate(picks):
            embed = chart_embed(game, song, chart)
            if i in jackets:
                name = f"jacket{i}.png"
                files.append(discord.File(str(jackets[i]), filename=name))
                embed.set_thumbnail(url=f"attachment://{name}")
            embeds.append(embed)
        await interaction.followup.send(embeds=embeds, files=files)

    # -------------------------------------------------------------- reach / what-if

    @tree.command(name="reach", description="목표 곡 레이팅에 필요한 점수를 계산합니다")
    @app_commands.describe(game="게임", const="보면 상수", target="목표 곡 레이팅 (예: maimai 300, CHUNITHM 16.5)")
    async def reach(interaction: discord.Interaction, game: GameChoice, const: float, target: float) -> None:
        need = tools.reach_score(game, const, target)
        if need is None:
            best = tools.chart_rating(game, const, 100.5 if game == "maimai" else 1_010_000)
            await interaction.response.send_message(
                f"상수 {const:.1f} 보면으로는 {target} 에 도달할 수 없어요. (최대 {tools.fmt_rating(game, best)})")
            return
        await interaction.response.send_message(
            f"상수 **{const:.1f}** 에서 레이팅 **{target}** 을 받으려면 **{tools.fmt_score(game, need)}** 이상이 필요해요.")

    async def _load_b50(interaction: discord.Interaction, game: str) -> B50 | None:
        from .bot import sega_b50

        token = bot.links.get_sega_token(interaction.user.id)
        if token is None:
            await interaction.followup.send("`/login` 으로 먼저 SEGA ID 로그인을 해 주세요.")
            return None
        result = await sega_b50(bot, game, interaction.user.id, token)
        if isinstance(result, str):
            await interaction.followup.send(result)
            return None
        return result

    @tree.command(name="whatif", description="이 곡에서 이 점수를 받으면 레이팅이 어떻게 바뀌는지 계산합니다")
    @app_commands.describe(game="게임", song="곡 제목", difficulty="난이도 (예: MAS, EXP, ULT, DX MAS, Re:MAS)",
                           score="maimai: 달성률 / CHUNITHM: 점수")
    @app_commands.autocomplete(song=song_autocomplete)
    async def whatif(interaction: discord.Interaction, game: GameChoice, song: str, difficulty: str,
                     score: float) -> None:
        found = _find_song(bot, game, song)
        chart = tools.find_chart(found, difficulty) if found else None
        if chart is None or not tools.playable(chart):
            await interaction.response.send_message("곡 또는 난이도를 찾지 못했어요.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        b50 = await _load_b50(interaction, game)
        if b50 is None:
            return
        is_new = tools.is_new_version(chart, bot.config.new_versions[game])
        result = tools.what_if(b50, found, chart, score, is_new)
        diff = result.after - result.before
        line = (f"**{found.title}** {tools.short(chart.difficulty)} ({chart.level_const:.1f}) 에서 "
                f"**{tools.fmt_score(game, score)}** → 곡 레이팅 **{result.entry.rating_text}**\n")
        if result.counted and diff > 0:
            line += (f"레이팅 {tools.fmt_rating(game, result.before)} → **{tools.fmt_rating(game, result.after)}** "
                     f"(+{tools.fmt_rating(game, diff)})")
        else:
            line += "B50에 들어가지 못해서 레이팅은 그대로예요."
        await interaction.followup.send(line)

    @tree.command(name="recommend", description="레이팅을 올리기 좋은 곡을 추천합니다")
    @app_commands.describe(game="게임")
    async def recommend_cmd(interaction: discord.Interaction, game: GameChoice) -> None:
        await interaction.response.defer(thinking=True)
        b50 = await _load_b50(interaction, game)
        if b50 is None:
            return
        recs = tools.recommend(bot.songdb, b50, bot.config.new_versions[game], 5)
        if not recs:
            await interaction.followup.send("추천할 곡을 찾지 못했어요.")
            return
        lines = [
            f"{_song_line(game, r.song, r.chart)} — {tools.fmt_score(game, r.target_score)} 받으면 "
            f"+{tools.fmt_rating(game, r.gain)}"
            for r in recs
        ]
        note = "평소 점수(B50 중앙값)로 이 곡들을 치면 B50의 가장 낮은 곡을 밀어낼 수 있어요."
        await interaction.followup.send(embed=discord.Embed(
            title=f"{GAME_NAMES[game]} 추천 곡", description="\n".join(lines) + f"\n\n{note}", color=COLORS[game]))

    # ----------------------------------------------------------------- guessing

    @tree.command(name="guess", description="자켓 일부를 보고 곡을 맞히는 게임을 시작합니다")
    @app_commands.describe(game="게임", level=f"문제로 낼 곡의 {tools.LEVEL_HELP} (선택)")
    async def guess(interaction: discord.Interaction, game: GameChoice, level: str | None = None) -> None:
        try:
            lo, hi = tools.parse_level(level, game) if level else (1.0, 16.0)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        channel_id = interaction.channel_id
        current = rounds.get(channel_id)
        if current and not current.answered and time.time() - current.started < GUESS_SECONDS:
            await interaction.response.send_message("이 채널에서 이미 게임이 진행 중이에요.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        pool = list({id(s): s for s, _ in tools.charts_in_range(bot.songdb, game, lo, hi)}.values())
        rng = random.Random()
        rng.shuffle(pool)
        for song in pool[:15]:
            paths = await bot.jackets.fetch(game, [song.jacket_key])
            if 0 in paths:
                break
        else:
            await interaction.followup.send("자켓을 불러오지 못했어요. 잠시 후 다시 해 주세요.")
            return
        rnd = GuessRound(game, song, str(paths[0]))
        rounds[channel_id] = rnd
        hint = await asyncio.to_thread(_crop_hint, rnd.jacket, rng)
        await interaction.followup.send(
            f"이 자켓의 곡은? `/answer` 로 답해 주세요. ({GUESS_SECONDS}초)",
            file=discord.File(io.BytesIO(hint), filename="guess.png"))

        async def timeout() -> None:
            await asyncio.sleep(GUESS_SECONDS)
            if rounds.get(channel_id) is rnd and not rnd.answered:
                rnd.answered = True
                channel = bot.get_channel(channel_id)
                if channel is not None:
                    await channel.send(f"시간 종료! 정답은 **{rnd.song.title}** 였어요.",
                                       file=discord.File(rnd.jacket, filename="answer.png"))

        asyncio.create_task(timeout())

    @tree.command(name="answer", description="자켓 맞히기 게임의 정답을 입력합니다")
    @app_commands.describe(title="곡 제목")
    async def answer(interaction: discord.Interaction, title: str) -> None:
        rnd = rounds.get(interaction.channel_id)
        if rnd is None or rnd.answered:
            await interaction.response.send_message("진행 중인 게임이 없어요. `/guess` 로 시작하세요.", ephemeral=True)
            return
        if _answer_matches(rnd.song, title):
            rnd.answered = True
            took = time.time() - rnd.started
            await interaction.response.send_message(
                f"{interaction.user.mention} 정답! **{rnd.song.title}** ({took:.1f}초)",
                file=discord.File(rnd.jacket, filename="answer.png"))
        else:
            await interaction.response.send_message(f"`{title}` 은(는) 아니에요.", ephemeral=True)

    # --------------------------------------------------------------------- help

    @tree.command(name="help", description="명령어 목록")
    async def help_cmd(interaction: discord.Interaction) -> None:
        groups = {
            "계정": ["/login — SEGA ID 로그인", "/logout — 로그인 정보 삭제", "/privacy — 다른 사람에게 공개 여부"],
            "기록": ["/b50 — 베스트 50 레이팅표", "/profile — 프로필 카드", "/recent — 최근 크레딧",
                   "/playlog on|off|test — 플레이 기록 자동 업로드"],
            "곡": ["/info — 곡 정보", "/jacket — 자켓", "/const — 상수별 보면 목록", "/random — 랜덤 선곡"],
            "계산": ["/calc — 곡 레이팅 계산", "/reach — 목표 레이팅에 필요한 점수",
                   "/whatif — 이 점수면 레이팅이 얼마나 오르나", "/recommend — 추천 곡"],
            "놀이": ["/guess — 자켓 맞히기", "/answer — 정답 입력"],
        }
        embed = discord.Embed(title="명령어", color=0x8A7CFF)
        for name, cmds in groups.items():
            embed.add_field(name=name, value="\n".join(cmds), inline=False)
        if bot.config.prefix:
            p = bot.config.prefix
            embed.set_footer(text=f"접두어로도 쓸 수 있어요: {p}b50 chuni · {p}info mai 곡이름 · "
                                  f"{p}playlog on chuni (게임: mai / chuni)")
        await interaction.response.send_message(embed=embed, ephemeral=True)
