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
from PIL import Image, ImageFilter

from . import answers, i18n, net_parsers, rating, render, tools
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


def _image(data: bytes, stem: str) -> discord.File:
    return discord.File(io.BytesIO(data), filename=render.filename(stem))


async def _jackets(bot: ChumaiBot, game: str, keys: list) -> dict:
    try:
        return await bot.jackets.fetch(game, keys)
    except Exception:
        log.warning("jacket fetch failed", exc_info=True)
        return {}


def _chart_row(song: CatalogSong, chart, jacket=None, **extra) -> dict:
    return {"title": song.title, "difficulty": chart.difficulty, "level": chart.level, "const": chart.level_const,
            "jacket": jacket, **extra}


SCORE_STEPS = {
    "chunithm": [1_010_000, 1_009_000, 1_007_500, 1_005_000, 1_000_000, 990_000, 975_000],
    "maimai": [100.5, 100.0, 99.5, 99.0, 98.0, 97.0, 94.0],
}


def _rank(game: str, score: float) -> str:
    return rating.maimai_rank(score) if game == "maimai" else rating.chunithm_rank(int(score))


def score_rows(game: str, const: float, mine: float | None = None,
               reach: float | None = None) -> list[tuple[str, str, str, bool]]:
    """Score -> rating table for a chart constant. `mine` is added and highlighted; with `reach`,
    every score that reaches that rating is highlighted."""
    steps = list(SCORE_STEPS[game])
    if mine is not None and mine not in steps:
        steps = sorted(steps + [mine], reverse=True)
    rows = []
    for score in steps:
        value = tools.chart_rating(game, const, score)
        rank = rating.maimai_rank(score) if game == "maimai" else rating.chunithm_rank(int(score))
        hl = score == mine if reach is None else float(value) >= reach - 1e-9
        rows.append((tools.fmt_score(game, score), rank, tools.fmt_rating(game, value), hl))
    return rows


def calc_image(game: str, const: float, score: float) -> bytes:
    value = tools.chart_rating(game, const, score)
    rank = rating.maimai_rank(score) if game == "maimai" else rating.chunithm_rank(int(score))
    return render.render_scores(game, "RATING", tools.fmt_rating(game, value),
                                f"상수 {const:.1f} · {tools.fmt_score(game, score)} ({rank})",
                                score_rows(game, const, mine=score))


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
    jacket: str | None  # shown with the answer
    started: float = field(default_factory=time.time)
    answered: bool = False

    def reveal(self) -> dict:
        return {"file": discord.File(self.jacket, filename="answer.png")} if self.jacket else {}


def _answer_matches(song: CatalogSong, answer: str, readings: list[str] = (), aliases: list[str] = ()) -> bool:
    """The title (or other titles), a long enough part of it, its reading in kana or Hangul, or a
    nickname registered with /alias (see answers.py)."""
    return answers.matches(answer, [song.title, *song.keys], readings, aliases)


def _crop_hint(path: str, rng: random.Random) -> bytes:
    with Image.open(path) as im:
        im = im.convert("RGB")
    size = int(min(im.size) * 0.35)
    x = rng.randint(0, im.width - size)
    y = rng.randint(0, im.height - size)
    hint = im.crop((x, y, x + size, y + size))
    if size < 200:  # blown up a lot: soften the jacket's compression blocks first
        hint = hint.filter(ImageFilter.GaussianBlur(0.6))
    hint = hint.resize((300, 300), Image.LANCZOS)
    return render.encode(hint)


GUESS_SECONDS = 60


def _give_up(rounds: dict[int, GuessRound], channel_id: int, who: str) -> tuple[str, dict] | None:
    """End the running round in `channel_id` and return the reveal message, or None if there is none."""
    rnd = rounds.get(channel_id)
    if rnd is None or rnd.answered:
        return None
    rnd.answered = True
    return f"{who} 님이 포기했어요. 정답은 **{rnd.song.title}** 였어요.", rnd.reveal()


class AnswerModal(discord.ui.Modal, title="정답 입력"):
    text = discord.ui.TextInput(label="곡 제목 (줄임말·한국어·별명도 돼요)", max_length=100)

    def __init__(self, submit):
        super().__init__()
        self.submit = submit

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.submit(interaction, self.text.value)


class GuessView(discord.ui.View):
    """Under the question: a button that opens a box to type the answer in, and one to give up."""

    def __init__(self, rounds: dict[int, GuessRound], channel_id: int, submit):
        super().__init__(timeout=GUESS_SECONDS)
        self.rounds = rounds
        self.channel_id = channel_id
        self.submit = submit  # (interaction, answer) -> checks it and replies

    @discord.ui.button(label="정답 입력", style=discord.ButtonStyle.primary)
    async def answer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        rnd = self.rounds.get(self.channel_id)
        if rnd is None or rnd.answered:
            await interaction.response.send_message("이미 끝난 게임이에요.", ephemeral=True)
            return
        await interaction.response.send_modal(AnswerModal(self.submit))

    @discord.ui.button(label="포기 · 정답 보기", style=discord.ButtonStyle.secondary)
    async def give_up(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        result = _give_up(self.rounds, self.channel_id, interaction.user.mention)
        if result is None:
            await interaction.response.send_message("이미 끝난 게임이에요.", ephemeral=True)
            return
        text, reveal = result
        self.stop()
        await interaction.response.send_message(text, **reveal)


CONST_LIMIT = 45 if render.LOW_MEMORY else 90  # charts shown in one /const image


# folders, short enough to sit under the rating gain on a /recommend tile
SHORT_GENRES = {
    "POPS＆アニメ": "POPS", "niconico＆ボーカロイド": "niconico", "東方Project": "東方",
    "ゲーム＆バラエティ": "GAME", "オンゲキ＆CHUNITHM": "オンゲキ", "宴会場": "宴",
}


def register(bot: ChumaiBot) -> None:
    from . import favorites

    favorites.register(bot)
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
        await interaction.followup.send(file=discord.File(io.BytesIO(png), filename=render.filename(f"profile_{game}")))

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
        await interaction.followup.send(file=discord.File(io.BytesIO(images[-1]), filename=render.filename(f"recent_{game}")))

    @tree.command(name="today", description="오늘(새벽 4시 기준) 플레이 정리: 크레딧별 곡, 신기록, 레이팅 변화 그래프")
    @app_commands.describe(game="게임")
    async def today(interaction: discord.Interaction, game: GameChoice) -> None:
        from .bot import render_today

        await interaction.response.defer(thinking=True)
        try:
            png = await render_today(bot, interaction.user.id, game)
        except SegaError as e:
            await interaction.followup.send(str(e))
            return
        if png is None:
            await interaction.followup.send("오늘 플레이 기록이 없어요.")
            return
        await interaction.followup.send(file=discord.File(io.BytesIO(png), filename=render.filename(f"today_{game}")))

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
        jacket = (await _jackets(bot, game, [found.jacket_key])).get(0)
        versions = sorted({c.display_version for c in found.charts if c.display_version})
        charts = [{"difficulty": c.difficulty, "level": c.level, "const": c.level_const}
                  if c.difficulty in tools.DIFF_ORDER else  # WORLD'S END: difficulty is e.g. 招☆4
                  {"difficulty": "WORLD'S END", "level": c.difficulty, "const": 0}
                  for c in tools.sort_charts(found.charts)]
        data = {"title": found.title, "artist": found.artist, "genre": found.genre, "versions": versions}
        png = await asyncio.to_thread(render.render_song, game, data, charts, jacket)
        await interaction.followup.send(file=_image(png, f"info_{game}"))

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
        await interaction.response.defer(thinking=True)
        shown = charts[:CONST_LIMIT]
        jackets = await _jackets(bot, game, [s.jacket_key for s, _ in shown])
        rows = [_chart_row(s, c, jackets.get(i), sub_line=s.genre) for i, (s, c) in enumerate(shown)]
        footer = f"외 {len(charts) - len(shown)}개 · 범위를 좁혀서 다시 검색해 보세요" if len(charts) > len(shown) else None
        png = await asyncio.to_thread(render.render_chart_list, game, "CONST", tools.describe_level(level, lo, hi),
                                      rows, f"{len(charts)}개", footer, 3, True)
        await interaction.followup.send(file=_image(png, f"const_{game}"))

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
        jackets = await _jackets(bot, game, [s.jacket_key for s, _ in picks])
        cards = [
            {"title": song.title, "artist": song.artist, "genre": song.genre, "difficulty": chart.difficulty,
             "level": chart.level, "const": chart.level_const, "jacket": jackets.get(i)}
            for i, (song, chart) in enumerate(picks)
        ]
        png = await asyncio.to_thread(render.render_random, game, cards, tools.describe_level(level, lo, hi))
        await interaction.followup.send(file=_image(png, f"random_{game}"))

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
        png = await asyncio.to_thread(
            render.render_scores, game, "REACH", tools.fmt_score(game, need),
            f"상수 {const:.1f} 에서 레이팅 {target} 을 받으려면 필요한 점수", score_rows(game, const, reach=target))
        await interaction.response.send_message(file=_image(png, f"reach_{game}"))

    async def _load_b50(interaction: discord.Interaction, game: str) -> B50 | None:
        from .bot import sega_b50

        token = bot.links.get_sega_token(interaction.user.id)
        if token is None:
            await interaction.followup.send("`/login` 으로 먼저 SEGA ID 로그인을 해 주세요.")
            return None
        result = await sega_b50(bot, game, interaction.user.id, token, images=False)
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
        before, after = tools.fmt_rating(game, result.before), tools.fmt_rating(game, result.after)
        if result.counted and diff > 0:
            headline = f"{before}  »  {after}"
            detail = f"{tools.fmt_score(game, score)} → 곡 레이팅 {result.entry.rating_text} · +{tools.fmt_rating(game, diff)}"
        else:
            headline = before
            detail = f"{tools.fmt_score(game, score)} → 곡 레이팅 {result.entry.rating_text} · B50에 못 들어가서 그대로예요"
        jacket = (await _jackets(bot, game, [found.jacket_key])).get(0)
        png = await asyncio.to_thread(render.render_scores, game, "WHAT IF", headline, detail,
                                      score_rows(game, chart.level_const, mine=score), _chart_row(found, chart, jacket))
        await interaction.followup.send(file=_image(png, f"whatif_{game}"))

    @tree.command(name="recommend", description="레이팅을 올리기 좋은 곡을 추천합니다")
    @app_commands.describe(game="게임")
    async def recommend_cmd(interaction: discord.Interaction, game: GameChoice) -> None:
        await interaction.response.defer(thinking=True)
        b50 = await _load_b50(interaction, game)
        if b50 is None:
            return
        recs = tools.recommend(bot.songdb, b50, bot.config.new_versions[game], 6)
        if not recs:
            await interaction.followup.send("추천할 곡을 찾지 못했어요.")
            return
        jackets = await _jackets(bot, game, [r.song.jacket_key for r in recs])
        rows = []
        for i, r in enumerate(recs):
            # just what to play and what to aim for
            if game == "chunithm":  # one chart moves the average by thousandths: show them
                right = f"+{float(r.raw_after - r.raw_before):.3f}"
            else:
                right = f"+{tools.fmt_rating(game, r.after - r.before)}"
            sub_line = f"목표 {_rank(game, r.target_score)}"
            # the exact score that still counts, unless it is the target itself (100.4999% for SSS+)
            if r.cut is not None and r.cut < r.target_score - (0.0001 if game == "maimai" else 1) - 1e-9:
                sub_line += f" · 최소 {tools.fmt_score(game, r.cut)}"
            if r.best is not None:
                sub_line += f" · 현재 {r.best:.2f}%" if game == "maimai" else f" · 현재 {tools.fmt_score(game, r.best)}"
            rows.append(_chart_row(
                r.song, r.chart, jackets.get(i), right=right, sub_line=sub_line,
                genre=SHORT_GENRES.get(r.song.genre, r.song.genre)))
        steps = tools.all_done_steps(b50, recs)
        done = tools.all_done(b50, recs)
        gain = f"+{float(steps[-1] - steps[0]):.3f}" if game == "chunithm" else \
            f"+{tools.fmt_rating(game, done.total - b50.total)}"
        progress = {
            "before": tools.fmt_rating(game, b50.total), "after": tools.fmt_rating(game, done.total), "gain": gain,
            "label": f"{len(recs)}곡 모두 목표 달성 시",
            "parts": [(float(b - a), r.chart.difficulty) for a, b, r in zip(steps, steps[1:], recs)],
        }
        png = await asyncio.to_thread(render.render_chart_list, game, "RECOMMEND", "FOR YOU", rows, None, None, 2,
                                      progress=progress)
        await interaction.followup.send(file=_image(png, f"recommend_{game}"))

    # ----------------------------------------------------------------- guessing

    def _busy(channel_id: int) -> bool:
        current = rounds.get(channel_id)
        return bool(current and not current.answered and time.time() - current.started < GUESS_SECONDS)

    async def _start_round(interaction: discord.Interaction, rnd: GuessRound, hint: bytes, question: str) -> None:
        channel_id = interaction.channel_id
        rounds[channel_id] = rnd
        await interaction.followup.send(
            f"{question} 아래 **정답 입력** 버튼이나 `/answer` 로 답해 주세요. ({GUESS_SECONDS}초)",
            file=_image(hint, "guess"), view=GuessView(rounds, channel_id, _submit))

        async def timeout() -> None:
            await asyncio.sleep(GUESS_SECONDS)
            if rounds.get(channel_id) is rnd and not rnd.answered:
                rnd.answered = True
                channel = bot.get_channel(channel_id)
                if channel is not None:
                    await channel.send(f"시간 종료! 정답은 **{rnd.song.title}** 였어요.", **rnd.reveal())

        asyncio.create_task(timeout())

    @tree.command(name="guess", description="자켓 일부를 보고 곡을 맞히는 게임을 시작합니다")
    @app_commands.describe(game="게임", level=f"문제로 낼 곡의 {tools.LEVEL_HELP} (선택)",
                           category=f"문제로 낼 곡의 {tools.CATEGORY_HELP} (선택)")
    async def guess(interaction: discord.Interaction, game: GameChoice, level: str | None = None,
                    category: str | None = None) -> None:
        if level and category is None and tools.parse_category(level, bot.songdb, game):
            level, category = None, level  # !guess chuni 동방
        genre = None
        if category:
            genre = tools.parse_category(category, bot.songdb, game)
            if genre is None:
                await interaction.response.send_message(
                    f"`{category}` 카테고리를 모르겠어요. {tools.CATEGORY_HELP}", ephemeral=True)
                return
        try:
            lo, hi = tools.parse_level(level, game) if level else (1.0, 16.0)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        if _busy(interaction.channel_id):
            await interaction.response.send_message("이 채널에서 이미 게임이 진행 중이에요.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        pool = list({id(s): s for s, _ in tools.charts_in_range(bot.songdb, game, lo, hi)
                     if genre is None or s.genre == genre}.values())
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
        hint = await asyncio.to_thread(_crop_hint, rnd.jacket, rng)
        await _start_round(interaction, rnd, hint, f"이 자켓의 곡은? ({genre})" if genre else "이 자켓의 곡은?")

    @tree.command(name="giveup", description="자켓 맞히기를 포기하고 정답을 봅니다 (접두어: !포기)")
    async def giveup(interaction: discord.Interaction) -> None:
        result = _give_up(rounds, interaction.channel_id, interaction.user.mention)
        if result is None:
            await interaction.response.send_message("진행 중인 게임이 없어요.", ephemeral=True)
            return
        text, reveal = result
        await interaction.response.send_message(text, **reveal)

    async def _submit(interaction: discord.Interaction, title: str) -> None:
        """Check an answer to the running round (from /answer or the answer button)."""
        rnd = rounds.get(interaction.channel_id)
        if rnd is None or rnd.answered:
            await interaction.response.send_message("진행 중인 게임이 없어요. `/guess` 로 시작하세요.", ephemeral=True)
            return
        guild_id = getattr(interaction, "guild_id", None) or 0
        nicknames = [*bot.links.aliases(guild_id, rnd.game, rnd.song.title),
                     *answers.community_aliases(rnd.game, rnd.song.title)]
        typed = " ".join(title.split()).replace("`", "'")  # shown in a code span: no markdown or mentions
        if _answer_matches(rnd.song, title, bot.jackets.reading(rnd.game, rnd.song.title), nicknames):
            rnd.answered = True
            took = time.time() - rnd.started
            await interaction.response.send_message(
                f"{interaction.user.mention} 정답! **{rnd.song.title}** ({took:.1f}초)\n입력한 답: `{typed}`",
                **rnd.reveal())
        else:
            await interaction.response.send_message(f"`{typed}` 은(는) 아니에요.", ephemeral=True)

    @tree.command(name="answer", description="자켓 맞히기 게임의 정답을 입력합니다")
    @app_commands.describe(title="곡 제목")
    async def answer(interaction: discord.Interaction, title: str) -> None:
        await _submit(interaction, title)

    alias = app_commands.Group(name="alias", description="맞히기 게임에서 정답으로 인정할 곡 별명 (이 서버)")

    async def _alias_song(interaction: discord.Interaction, game: str, song: str) -> CatalogSong | None:
        found = _find_song(bot, game, song)
        if found is None:
            await interaction.response.send_message("곡을 찾지 못했어요.", ephemeral=True)
        return found

    @alias.command(name="add", description="곡 별명을 등록합니다 (예: 脳漿炸裂ガール → 뇌장작렬걸)")
    @app_commands.describe(game="게임", song="곡 제목", name="별명")
    @app_commands.autocomplete(song=song_autocomplete)
    async def alias_add(interaction: discord.Interaction, game: GameChoice, song: str, name: str) -> None:
        found = await _alias_song(interaction, game, song)
        if found is None:
            return
        name = " ".join(name.split())
        if not answers.fold(name) or len(name) > 40:
            await interaction.response.send_message("별명은 글자나 숫자가 들어간 40자 이하로 써 주세요.", ephemeral=True)
            return
        guild_id = getattr(interaction, "guild_id", None) or 0
        if bot.links.add_alias(guild_id, game, found.title, name):
            await interaction.response.send_message(f"**{found.title}** 의 별명으로 `{name}` 을(를) 등록했어요.")
        else:
            await interaction.response.send_message("이미 등록된 별명이에요.", ephemeral=True)

    @alias.command(name="remove", description="등록한 곡 별명을 지웁니다")
    @app_commands.describe(game="게임", song="곡 제목", name="지울 별명")
    @app_commands.autocomplete(song=song_autocomplete)
    async def alias_remove(interaction: discord.Interaction, game: GameChoice, song: str, name: str) -> None:
        found = await _alias_song(interaction, game, song)
        if found is None:
            return
        guild_id = getattr(interaction, "guild_id", None) or 0
        if bot.links.remove_alias(guild_id, game, found.title, " ".join(name.split())):
            await interaction.response.send_message(f"**{found.title}** 의 별명 `{name}` 을(를) 지웠어요.")
        else:
            await interaction.response.send_message("그런 별명이 없어요.", ephemeral=True)

    @alias.command(name="list", description="곡에 등록된 별명을 봅니다")
    @app_commands.describe(game="게임", song="곡 제목")
    @app_commands.autocomplete(song=song_autocomplete)
    async def alias_list(interaction: discord.Interaction, game: GameChoice, song: str) -> None:
        found = await _alias_song(interaction, game, song)
        if found is None:
            return
        names = bot.links.aliases(getattr(interaction, "guild_id", None) or 0, game, found.title)
        text = ", ".join(f"`{n}`" for n in names) if names else "없음"
        await interaction.response.send_message(f"**{found.title}** 별명: {text}", ephemeral=True)

    tree.add_command(alias)

    # --------------------------------------------------------------------- help

    @tree.command(name="help", description="명령어 목록")
    async def help_cmd(interaction: discord.Interaction) -> None:
        from .prefix import ALIASES

        locale = getattr(interaction, "locale", None)  # none for a prefix command
        groups = {
            "계정": [("login", "SEGA ID 로그인"), ("logout", "로그인 정보 삭제"), ("privacy", "다른 사람에게 공개 여부")],
            "기록": [("b50", "베스트 50 레이팅표"), ("profile", "프로필 카드"), ("recent", "최근 크레딧"), ("today", "오늘 플레이 정리"),
                   ("playlog", "켜기|끄기|테스트|전체 — 플레이 기록 자동 업로드" if locale is discord.Locale.korean
                    else "on|off|test|all — 플레이 기록 자동 업로드")],
            "곡": [("info", "곡 정보"), ("jacket", "자켓"), ("const", "상수별 보면 목록"), ("random", "랜덤 선곡")],
            "계산": [("calc", "곡 레이팅 계산"), ("reach", "목표 레이팅에 필요한 점수"),
                   ("whatif", "이 점수면 레이팅이 얼마나 오르나"), ("recommend", "추천 곡")],
            "놀이": [("guess", "자켓 맞히기"), ("answer", "정답 입력"), ("alias", "곡 별명 등록"),
                   ("giveup", "포기하고 정답 보기")],
        }
        if getattr(bot, "site", None) is not None and bot.site.enabled:
            groups["기록 사이트"] = [
                ("site", "연결|연결끊기|올리기 — 기록 사이트 연동" if locale is discord.Locale.korean
                 else "link|unlink|sync — 기록 사이트 연동"),
                ("favorite", "즐겨찾기 프리셋 (연결하면 사이트와 같이 써요)"),
            ]
        p = bot.config.prefix
        short = {full: alias for alias, full in ALIASES.items()}
        embed = discord.Embed(title="명령어", color=0x8A7CFF)
        for name, cmds in groups.items():
            lines = []
            for cmd, desc in cmds:
                alias = f" · `{p}{short[cmd]}`" if p and cmd in short else ""
                lines.append(f"/{i18n.command_name(cmd, locale)}{alias} — {desc}")
            embed.add_field(name=name, value="\n".join(lines), inline=False)
        from . import updater

        footer = (f"접두어 예시: {p}b c · {p}r m 13+ · {p}i c 곡이름 · {p}오늘 츄니 · {p}플레이로그 켜기 마이 "
                  f"(게임: m / mai / 마이 / c / chuni / 츄니, 한국어 명령어 이름도 돼요)") if p else ""
        if updater.enabled():
            footer += f"\n버전 {await updater.version()}"
        if footer:
            embed.set_footer(text=footer.strip())
        await interaction.response.send_message(embed=embed, ephemeral=True)
