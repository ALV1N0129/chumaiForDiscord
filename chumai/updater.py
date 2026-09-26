"""Pull new commits from GitHub and ask start.bat to restart the bot."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger(__name__)

RESTART_EXIT_CODE = 3
REPO = Path(__file__).resolve().parent.parent


async def _git(*args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=REPO, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode(errors="replace").strip()


def enabled() -> bool:
    return (REPO / ".git").exists()


async def pull_if_updated() -> bool:
    """Return True if new commits were pulled."""
    code, out = await _git("fetch", "--quiet")
    if code != 0:
        log.warning("git fetch failed: %s", out)
        return False
    _, local = await _git("rev-parse", "HEAD")
    code, remote = await _git("rev-parse", "@{u}")
    if code != 0 or local == remote:
        return False
    code, out = await _git("pull", "--ff-only")
    if code != 0:
        log.warning("git pull failed: %s", out)
        return False
    log.info("updated to %s", remote[:7])
    return True
