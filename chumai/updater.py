"""Pull new commits from GitHub and ask start.bat to restart the bot."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

RESTART_EXIT_CODE = 3
REPO = Path(__file__).resolve().parent.parent


async def _git(*args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=REPO, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "git timed out (waiting for a login prompt?)"
    return proc.returncode, out.decode(errors="replace").strip()


def enabled() -> bool:
    return (REPO / ".git").exists()


async def check() -> tuple[bool, str]:
    """Pull new commits. Returns (pulled, message for the owner)."""
    code, out = await _git("fetch", "--quiet")
    if code != 0:
        log.warning("git fetch failed: %s", out)
        return False, f"GitHub에서 받아오지 못했어요: {out[:300]}"
    _, branch = await _git("rev-parse", "--abbrev-ref", "HEAD")
    _, local = await _git("rev-parse", "--short", "HEAD")
    code, remote = await _git("rev-parse", "--short", "@{u}")
    if code != 0:
        return False, f"`{branch}` 브랜치에 연결된 GitHub 브랜치가 없어요: {remote[:200]}"
    if local == remote:
        return False, f"이미 최신 버전이에요. (`{branch}` @ `{local}`)"
    code, out = await _git("pull", "--ff-only")
    if code != 0:
        log.warning("git pull failed: %s", out)
        return False, (f"새 버전(`{remote}`)이 있지만 받지 못했어요. 지금 `{local}` 이에요.\n"
                       f"```{out[:900]}```\n봇 폴더에서 `git status` 로 바뀐 파일이 있는지 확인해 주세요.")
    log.info("updated %s -> %s", local, remote)
    return True, f"`{local}` → `{remote}` 로 업데이트했어요. 몇 초 뒤 재시작돼요."


async def pull_if_updated() -> bool:
    """Return True if new commits were pulled."""
    return (await check())[0]


async def version() -> str:
    code, out = await _git("log", "-1", "--format=%h %cd", "--date=format:%m/%d %H:%M")
    return out if code == 0 else "?"
