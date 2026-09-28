"""Prefix commands (e.g. `!b50 chuni`) that reuse the slash command handlers.

A chat message is parsed against the slash command's parameters and passed to the same
callback through a small stand-in for `discord.Interaction`.
"""

from __future__ import annotations

import logging
import shlex
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import discord
from discord import AppCommandOptionType, app_commands

if TYPE_CHECKING:
    from .bot import ChumaiBot

log = logging.getLogger(__name__)

GAME_ALIASES = {
    "maimai": "maimai", "mai": "maimai", "m": "maimai", "마이마이": "maimai", "마이": "maimai",
    "chunithm": "chunithm", "chuni": "chunithm", "c": "chunithm", "츄니즘": "chunithm", "츄니": "chunithm",
}
# short names for prefix commands
ALIASES = {
    "b": "b50", "p": "profile", "rc": "recent", "i": "info", "j": "jacket", "c": "const", "r": "random",
    "rh": "reach", "w": "whatif", "rec": "recommend", "cal": "calc", "g": "guess", "cg": "chartguess", "a": "answer",
    "h": "help", "pl": "playlog",
}
TRUE = {"true", "yes", "on", "1", "y", "켜기", "공개"}
FALSE = {"false", "no", "off", "0", "n", "끄기", "비공개"}


class UsageError(Exception):
    pass


def _reply_kwargs(**kw: Any) -> dict[str, Any]:
    return {k: v for k, v in kw.items() if v is not None and v != []}


class _Response:
    def __init__(self, message: discord.Message):
        self._message = message
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def send_message(self, content: str | None = None, *, embed=None, file=None, view=None, embeds=None,
                           files=None, ephemeral: bool = False, **_: Any) -> None:
        self._done = True
        kwargs = _reply_kwargs(embed=embed, file=file, view=view, embeds=embeds, files=files)
        await self._message.reply(content, mention_author=False, **kwargs)

    async def defer(self, **_: Any) -> None:
        self._done = True
        try:
            await self._message.channel.typing()
        except Exception:
            pass

    async def send_modal(self, modal) -> None:  # pragma: no cover - guarded by the login command
        raise UsageError("이 명령어는 슬래시 명령어로 써 주세요.")


class _Followup:
    def __init__(self, message: discord.Message):
        self._message = message

    async def send(self, content: str | None = None, *, embed=None, file=None, view=None, embeds=None,
                   files=None, ephemeral: bool = False, **_: Any) -> None:
        kwargs = _reply_kwargs(embed=embed, file=file, view=view, embeds=embeds, files=files)
        await self._message.reply(content, mention_author=False, **kwargs)


class MessageInteraction:
    """Just enough of `discord.Interaction` for our command callbacks."""

    def __init__(self, bot: ChumaiBot, message: discord.Message):
        self.client = bot
        self.user = message.author
        self.channel = message.channel
        self.channel_id = message.channel.id
        self.guild = message.guild
        self.message = message
        self.namespace = SimpleNamespace()
        self.response = _Response(message)
        self.followup = _Followup(message)


def _convert(param: app_commands.Parameter, raw: str, message: discord.Message) -> Any:
    if param.choices:
        values = [str(c.value) for c in param.choices]
        value = GAME_ALIASES.get(raw.lower(), raw) if param.name == "game" else raw
        if value not in values:
            raise UsageError(f"`{param.name}` 은(는) {' / '.join(values)} 중 하나여야 해요.")
        return value
    t = param.type
    try:
        if t is AppCommandOptionType.integer:
            value = int(raw.replace(",", ""))
        elif t is AppCommandOptionType.number:
            value = float(raw.replace(",", "").rstrip("%"))
        elif t is AppCommandOptionType.boolean:
            if raw.lower() in TRUE:
                return True
            if raw.lower() in FALSE:
                return False
            raise ValueError
        elif t is AppCommandOptionType.user:
            if message.mentions:
                return message.mentions[0]
            raise ValueError
        else:
            return raw
    except ValueError:
        raise UsageError(f"`{param.name}` 값이 올바르지 않아요: {raw}") from None
    if param.min_value is not None and value < param.min_value:
        raise UsageError(f"`{param.name}` 은(는) {param.min_value} 이상이어야 해요.")
    if param.max_value is not None and value > param.max_value:
        raise UsageError(f"`{param.name}` 은(는) {param.max_value} 이하여야 해요.")
    return value


def _is_mention(token: str) -> bool:
    return token.startswith("<@") and token.endswith(">")


def parse_args(command: app_commands.Command, tokens: list[str], message: discord.Message) -> dict[str, Any]:
    """Map tokens onto the command's parameters.

    A text parameter takes as many words as it can while leaving one word for each
    required parameter after it, so `!whatif chuni aleph zero MAS 1009000` works.
    """
    params = list(command.parameters)
    kwargs: dict[str, Any] = {}
    i = 0
    for n, param in enumerate(params):
        rest = params[n + 1:]
        if param.type is AppCommandOptionType.user:
            if i < len(tokens) and _is_mention(tokens[i]):
                kwargs[param.name] = _convert(param, tokens[i], message)
                i += 1
            elif param.required:
                raise UsageError(f"`{param.name}` 에 유저를 멘션해 주세요.")
            continue
        if i >= len(tokens):
            if param.required:
                raise UsageError(f"`{param.name}` 이(가) 필요해요.")
            continue
        if param.type is AppCommandOptionType.string and not param.choices:
            # leave one word for every later (non-mention) parameter
            reserve = sum(1 for p in rest if p.type is not AppCommandOptionType.user)
            take = max(1, len(tokens) - i - reserve)
            kwargs[param.name] = " ".join(tokens[i:i + take])
            i += take
        else:
            kwargs[param.name] = _convert(param, tokens[i], message)
            i += 1
    if i < len(tokens):
        raise UsageError(f"필요 없는 값이 있어요: {' '.join(tokens[i:])}")
    return kwargs


def usage(prefix: str, name: str, command: app_commands.Command) -> str:
    parts = [f"{prefix}{name}"]
    for p in command.parameters:
        parts.append(f"<{p.name}>" if p.required else f"[{p.name}]")
    return " ".join(parts)


class LoginView(discord.ui.View):
    """`!login` can't open a form from a chat message, so it offers a button that does."""

    def __init__(self, bot: ChumaiBot, owner_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.owner_id = owner_id

    @discord.ui.button(label="SEGA ID 로그인", style=discord.ButtonStyle.primary)
    async def open(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        from .bot import SegaLoginModal

        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("명령어를 입력한 사람만 쓸 수 있어요.", ephemeral=True)
            return
        await interaction.response.send_modal(SegaLoginModal(self.bot))


async def handle(bot: ChumaiBot, message: discord.Message, prefix: str) -> None:
    try:
        tokens = shlex.split(message.content[len(prefix):])
    except ValueError:
        tokens = message.content[len(prefix):].split()
    if not tokens:
        return
    name = tokens.pop(0).lower()
    name = ALIASES.get(name, name)
    command = bot.tree.get_command(name)
    if command is None:
        return
    shown = name
    if isinstance(command, app_commands.Group):
        if not tokens:
            subs = " / ".join(c.name for c in command.commands)
            await message.reply(f"`{prefix}{name} <{subs}>` 형식으로 써 주세요.", mention_author=False)
            return
        sub = tokens.pop(0).lower()
        command = command.get_command(sub)
        if command is None:
            return
        shown = f"{name} {sub}"

    if name == "login":
        await message.reply("아래 버튼을 눌러 로그인해 주세요. 비밀번호는 채팅에 쓰지 마세요!",
                            view=LoginView(bot, message.author.id), mention_author=False)
        return

    try:
        kwargs = parse_args(command, tokens, message)
    except UsageError as e:
        await message.reply(f"{e}\n사용법: `{usage(prefix, shown, command)}`", mention_author=False)
        return
    interaction = MessageInteraction(bot, message)
    interaction.namespace = SimpleNamespace(**kwargs)
    try:
        await command.callback(interaction, **kwargs)
    except UsageError as e:
        await message.reply(str(e), mention_author=False)
    except Exception:
        log.exception("prefix command %s failed", shown)
        await message.reply("명령어를 처리하다 오류가 났어요.", mention_author=False)
