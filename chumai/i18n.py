"""Korean names for the slash commands and their options. Discord shows them to people whose app is
set to Korean; everyone else sees the English names. Descriptions are already in Korean."""

from __future__ import annotations

import discord
from discord import app_commands

COMMANDS = {
    # commands and groups
    "login": "로그인",
    "logout": "로그아웃",
    "privacy": "공개설정",
    "playlog": "플레이로그",
    "logs": "봇로그",
    "update": "업데이트",
    "calc": "계산",
    "profile": "프로필",
    "recent": "최근",
    "today": "오늘",
    "info": "곡정보",
    "jacket": "자켓",
    "const": "상수표",
    "random": "랜덤",
    "reach": "목표점수",
    "whatif": "만약",
    "recommend": "추천",
    "guess": "자켓맞히기",
    "giveup": "포기",
    "answer": "정답",
    "alias": "별명",
    "help": "도움말",
    # subcommands
    "on": "켜기",
    "off": "끄기",
    "test": "테스트",
    "status": "상태",
    "live": "실시간",
    "add": "추가",
    "remove": "삭제",
    "list": "목록",
    "all": "전체",
}

OPTIONS = {
    "game": "게임",
    "member": "유저",
    "public": "공개",
    "song": "곡",
    "level": "레벨",
    "count": "개수",
    "const": "상수",
    "target": "목표",
    "difficulty": "난이도",
    "score": "점수",
    "title": "제목",
    "name": "별명",
    "switch": "켜기끄기",
}


class KoreanNames(app_commands.Translator):
    async def translate(self, string: app_commands.locale_str, locale: discord.Locale,
                        context: app_commands.TranslationContext) -> str | None:
        if locale is not discord.Locale.korean:
            return None
        where = context.location
        if where in (app_commands.TranslationContextLocation.command_name,
                     app_commands.TranslationContextLocation.group_name):
            return COMMANDS.get(string.message)
        if where is app_commands.TranslationContextLocation.parameter_name:
            return OPTIONS.get(string.message)
        return None


def command_name(name: str, locale: discord.Locale | None) -> str:
    """How the command reads in someone's Discord: Korean if their app is."""
    return COMMANDS.get(name, name) if locale is discord.Locale.korean else name
