"""Jackets sent from a PC (tools/export_jackets.py --upload) to a webhook the bot made: saved into the
jacket folder as hq_<music id>.jpg, which the bot prefers over downloading.

Only messages from that one webhook are taken (its id is in the settings), only zip files, and only
entries named like hq_123.jpg that are JPEGs of a sane size."""

from __future__ import annotations

import asyncio
import io
import logging
import re
import zipfile
from pathlib import Path

import discord

log = logging.getLogger(__name__)

WEBHOOK_SETTING = "jacket_upload_webhook"
WEBHOOK_NAME = "chumai jackets"
NAME = re.compile(r"^hq_\d{1,6}\.jpg$")
MAX_ZIP = 25 * 1024 * 1024
MAX_JACKET = 2 * 1024 * 1024


def save_zip(data: bytes, folder: Path) -> int:
    """Save the jackets in a zip into `folder`; returns how many."""
    folder.mkdir(parents=True, exist_ok=True)
    saved = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            name = info.filename.rsplit("/", 1)[-1]
            if not NAME.match(name) or info.file_size > MAX_JACKET:
                continue
            body = z.read(info)
            if not body.startswith(b"\xff\xd8"):  # not a JPEG
                continue
            (folder / name).write_bytes(body)
            saved += 1
    return saved


async def accept(bot, message: discord.Message) -> bool:
    """Take the jackets in a message from the upload webhook. True if it was one (handled)."""
    expected = bot.links.get_setting(WEBHOOK_SETTING)
    if not expected or str(message.webhook_id) != expected:
        return False
    folder = Path(bot.config.jacket_dir) / "chunithm"
    total = 0
    for att in message.attachments:
        if not att.filename.endswith(".zip") or att.size > MAX_ZIP:
            continue
        try:
            data = await att.read()
            total += await asyncio.to_thread(save_zip, data, folder)
            del data
        except Exception:
            log.warning("could not save uploaded jackets %s", att.filename, exc_info=True)
    log.info("saved %d uploaded jackets", total)
    try:
        await message.add_reaction("✅" if total else "⚠️")
    except discord.HTTPException:
        pass
    return True


async def make_webhook(bot, channel) -> str:
    """A new upload webhook in `channel` (the old one deleted); returns its URL."""
    old = bot.links.get_setting(WEBHOOK_SETTING)
    if old:
        try:
            await (await bot.fetch_webhook(int(old))).delete()
        except (discord.HTTPException, ValueError):
            pass
    hook = await channel.create_webhook(name=WEBHOOK_NAME)
    bot.links.set_setting(WEBHOOK_SETTING, str(hook.id))
    return hook.url
