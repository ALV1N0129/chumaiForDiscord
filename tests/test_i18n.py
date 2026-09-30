import asyncio
import re

import discord
from discord import app_commands

from chumai import i18n

# what Discord takes as a command or option name (lowercase where there is a case)
NAME = re.compile(r"^[-_\w]{1,32}$")


def test_korean_names_are_valid_and_distinct():
    for names in (i18n.COMMANDS, i18n.OPTIONS):
        for name in names.values():
            assert NAME.match(name) and name == name.lower(), name
    top = [ko for en, ko in i18n.COMMANDS.items() if en not in ("on", "off", "test", "status", "live", "add",
                                                                  "remove", "list")]
    assert len(top) == len(set(top))


def test_translator_answers_only_korean():
    t = i18n.KoreanNames()
    ctx = app_commands.TranslationContext(app_commands.TranslationContextLocation.command_name, None)
    assert asyncio.run(t.translate(app_commands.locale_str("today"), discord.Locale.korean, ctx)) == "오늘"
    assert asyncio.run(t.translate(app_commands.locale_str("today"), discord.Locale.japanese, ctx)) is None
    assert i18n.command_name("today", discord.Locale.korean) == "오늘"
    assert i18n.command_name("b50", discord.Locale.korean) == "b50"
    assert i18n.command_name("today", discord.Locale.american_english) == "today"


def test_every_command_and_option_has_a_korean_name(tmp_path, monkeypatch):
    from test_features_commands import _bot

    bot = _bot(tmp_path, monkeypatch)
    translator = i18n.KoreanNames()

    async def payloads():
        await bot.tree.set_translator(translator)
        return [await c.get_translated_payload(bot.tree, translator) for c in bot.tree.get_commands()]

    missing = []

    def walk(item):
        if item["name"] != "b50" and "ko" not in item.get("name_localizations", {}):
            missing.append(item["name"])
        for option in item.get("options", []):
            if option.get("type", 3) in (1, 2) or "name" in option:
                walk(option)

    for payload in asyncio.run(payloads()):
        walk(payload)
    assert missing == []
