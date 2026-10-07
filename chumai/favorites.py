"""Favorite song presets for maimai DX NET (/favorite): save the favorites as a named list, make one
from song names, and put one on the site (at most 30 songs, the site's limit)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from . import answers, net_parsers
from .segaid import NetClient, SegaError
from .songdb import normalize_title, search

if TYPE_CHECKING:
    from .bot import ChumaiBot

log = logging.getLogger(__name__)

PAGE = "/maimai-mobile/home/userOption/favorite/updateMusic"
SET = PAGE + "/set"
LIMIT = 30  # the site takes this many favorites
GENRES = {1: "POPS＆ANIME", 2: "niconico＆VOCALOID", 3: "東方Project", 4: "GAME＆VARIETY", 5: "maimai",
          6: "オンゲキ＆CHUNITHM"}


def resolve(bot, guild_id: int, rows: list[net_parsers.FavoriteRow], query: str) -> net_parsers.FavoriteRow | None:
    """The song on the page `query` names: its title, a search hit, or a nickname."""
    key = normalize_title(query)
    exact = [r for r in rows if normalize_title(r.title) == key]
    if exact:
        return exact[0]
    by_title = {normalize_title(r.title): r for r in rows}
    for song in search(bot.songdb, "maimai", query, 3):
        if normalize_title(song.title) in by_title:
            return by_title[normalize_title(song.title)]
    hits = []
    for r in rows:
        nicknames = [*bot.links.aliases(guild_id, "maimai", r.title), *answers.community_aliases("maimai", r.title)]
        if answers.matches(query, [r.title], bot.jackets.reading("maimai", r.title), nicknames):
            hits.append(r)
    return hits[0] if len({h.title for h in hits}) == 1 else None


def pick(rows: list[net_parsers.FavoriteRow], songs: list) -> tuple[list[net_parsers.FavoriteRow], list[str]]:
    """The page rows of a preset's [title, genre] songs, and the titles no longer on the page."""
    found, missing = [], []
    for title, genre in songs:
        same = [r for r in rows if r.title == title]
        row = next((r for r in same if r.genre == genre), same[0] if same else None)
        (found if row else missing).append(row or title)
    return found, missing


def _songs_text(songs: list) -> str:
    return "\n".join(f"{i}. {title}" for i, (title, _) in enumerate(songs, 1))


def register(bot: ChumaiBot) -> None:
    tree = bot.tree
    group = app_commands.Group(name="favorite", description="maimai 즐겨찾기 곡 프리셋 (저장해 두고 바꿔 끼우기)")

    async def page(interaction: discord.Interaction):
        token = bot.links.get_sega_token(interaction.user.id)
        if token is None:
            raise SegaError("`/login` 으로 먼저 SEGA ID 로그인을 해 주세요.")
        return token

    async def fetch_rows(net: NetClient) -> list[net_parsers.FavoriteRow]:
        rows = net_parsers.parse_maimai_favorites(await net.get(PAGE))
        if not rows:
            raise SegaError("즐겨찾기 페이지를 읽지 못했어요.")
        return rows

    def keep_token(interaction, net, token) -> None:
        if net.clal != token:
            bot.links.set_sega_token(interaction.user.id, net.clal)

    @group.command(name="save", description="지금 게임에 걸린 즐겨찾기를 프리셋으로 저장합니다")
    @app_commands.describe(name="프리셋 이름")
    @app_commands.rename(name="preset")
    async def fav_save(interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            token = await page(interaction)
            async with NetClient("maimai", token) as net:
                rows = await fetch_rows(net)
            keep_token(interaction, net, token)
        except SegaError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        songs = [[r.title, r.genre] for r in rows if r.checked]
        if not songs:
            await interaction.followup.send("지금 걸린 즐겨찾기가 없어요.", ephemeral=True)
            return
        bot.links.save_preset(interaction.user.id, "maimai", name, songs)
        await interaction.followup.send(f"프리셋 **{name}** 저장 ({len(songs)}곡)\n{_songs_text(songs)}", ephemeral=True)

    @group.command(name="make", description="곡 이름(별명 가능)으로 프리셋을 만듭니다. 쉼표로 구분")
    @app_commands.rename(name="preset")
    @app_commands.describe(name="프리셋 이름", songs="곡들, 쉼표로 구분 (예: 꽃눈베, 돈파뮤, Xaleid◆scopiX)")
    async def fav_make(interaction: discord.Interaction, name: str, songs: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            token = await page(interaction)
            async with NetClient("maimai", token) as net:
                rows = await fetch_rows(net)
            keep_token(interaction, net, token)
        except SegaError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        guild_id = getattr(interaction, "guild_id", None) or 0
        chosen, unknown = [], []
        for q in [q.strip() for q in songs.replace("\n", ",").split(",") if q.strip()]:
            row = resolve(bot, guild_id, rows, q)
            if row is None:
                unknown.append(q)
            elif [row.title, row.genre] not in chosen:
                chosen.append([row.title, row.genre])
        if not chosen:
            await interaction.followup.send("곡을 하나도 찾지 못했어요.", ephemeral=True)
            return
        bot.links.save_preset(interaction.user.id, "maimai", name, chosen)
        text = f"프리셋 **{name}** 저장 ({len(chosen)}곡)\n{_songs_text(chosen)}"
        if len(chosen) > LIMIT:
            text += f"\n게임 즐겨찾기는 {LIMIT}곡까지라 적용하면 앞의 {LIMIT}곡만 걸려요."
        if unknown:
            text += f"\n찾지 못한 곡: {', '.join(unknown)}"
        await interaction.followup.send(text[:1990], ephemeral=True)

    @group.command(name="apply", description="저장한 프리셋으로 게임 즐겨찾기를 바꿉니다")
    @app_commands.describe(name="프리셋 이름")
    @app_commands.rename(name="preset")
    async def fav_apply(interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        songs = bot.links.get_preset(interaction.user.id, "maimai", name)
        if songs is None:
            await interaction.followup.send(f"**{name}** 프리셋이 없어요. `/favorite list` 로 확인해 주세요.",
                                            ephemeral=True)
            return
        try:
            token = await page(interaction)
            async with NetClient("maimai", token) as net:
                rows = await fetch_rows(net)
                found, missing = pick(rows, songs)
                found = found[:LIMIT]
                await net.post(SET, [("idx", "99"), *[("music[]", r.value) for r in found]])
                now = [r for r in await fetch_rows(net) if r.checked]  # what the site has now
            keep_token(interaction, net, token)
        except SegaError as e:
            await interaction.followup.send(f"바꾸지 못했어요: {e}", ephemeral=True)
            return
        log.info("favorite preset applied: %d songs", len(now))
        text = f"즐겨찾기를 **{name}** 으로 바꿨어요. (지금 {len(now)}곡)"
        if len(songs) > LIMIT:
            text += f"\n{LIMIT}곡까지만 걸 수 있어서 뒤의 {len(songs) - LIMIT}곡은 빠졌어요."
        if missing:
            text += f"\n게임에서 찾지 못한 곡: {', '.join(missing)}"
        await interaction.followup.send(text[:1990], ephemeral=True)

    @group.command(name="list", description="저장한 프리셋 목록 (이름을 주면 그 프리셋의 곡들)")
    @app_commands.describe(name="볼 프리셋 이름 (선택)")
    @app_commands.rename(name="preset")
    async def fav_list(interaction: discord.Interaction, name: str | None = None) -> None:
        if name:
            songs = bot.links.get_preset(interaction.user.id, "maimai", name)
            text = f"**{name}** ({len(songs)}곡)\n{_songs_text(songs)}" if songs else f"**{name}** 프리셋이 없어요."
        else:
            presets = bot.links.presets(interaction.user.id, "maimai")
            text = ("\n".join(f"· **{n}** ({len(s)}곡)" for n, s in presets) if presets else
                    "저장한 프리셋이 없어요. `/favorite save` 나 `/favorite make` 로 만들어 보세요.")
        await interaction.response.send_message(text[:1990], ephemeral=True)

    @group.command(name="delete", description="프리셋을 지웁니다")
    @app_commands.describe(name="프리셋 이름")
    @app_commands.rename(name="preset")
    async def fav_delete(interaction: discord.Interaction, name: str) -> None:
        ok = bot.links.delete_preset(interaction.user.id, "maimai", name)
        await interaction.response.send_message(f"**{name}** 을(를) 지웠어요." if ok else f"**{name}** 프리셋이 없어요.",
                                                ephemeral=True)

    async def preset_names(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return [app_commands.Choice(name=n, value=n) for n, _ in bot.links.presets(interaction.user.id, "maimai")
                if current.lower() in n.lower()][:25]

    for cmd in (fav_apply, fav_list, fav_delete):
        cmd.autocomplete("name")(preset_names)
    tree.add_command(group)
