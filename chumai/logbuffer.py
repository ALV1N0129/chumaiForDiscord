"""The latest log lines kept in memory, so the bot's owner can read them with /logs from Discord
(the host's console isn't always at hand). Only the bot's own messages and warnings from any library
are kept; an exception is shortened to its last line."""

from __future__ import annotations

import logging
from collections import deque

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class RecentLogs(logging.Handler):
    def __init__(self, size: int = 200):
        super().__init__(logging.INFO)
        self.lines: deque[str] = deque(maxlen=size)
        # lines not yet sent to the live log channel; Discord's own messages stay out, so a failure
        # to send them can't feed itself
        self.pending: deque[str] = deque(maxlen=500)
        self.setFormatter(logging.Formatter(FORMAT, "%m-%d %H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING and not record.name.startswith("chumai"):
            return  # discord.py's own INFO chatter
        try:
            exc = record.exc_info
            record.exc_info, record.exc_text = None, None  # the full traceback stays in the console
            line = self.format(record)
            if exc and exc[1] is not None:
                line += f" [{type(exc[1]).__name__}: {exc[1]}]"
            record.exc_info = exc
            self.lines.append(line[:400])
            if not record.name.startswith(("discord", "chumai.live")):
                self.pending.append(line[:400])
        except Exception:
            self.handleError(record)

    def tail(self, count: int) -> list[str]:
        return list(self.lines)[-count:]

    def take(self, limit: int = 1900) -> str:
        """Pending lines for one message, oldest first, up to `limit` characters ("" if none)."""
        out: list[str] = []
        size = 0
        while self.pending and size + len(self.pending[0]) + 1 <= limit:
            line = self.pending.popleft()
            out.append(line)
            size += len(line) + 1
        return "\n".join(out)


recent = RecentLogs()
