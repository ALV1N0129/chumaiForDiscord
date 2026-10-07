"""Pull new commits from GitHub and ask start.bat to restart the bot."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

RESTART_EXIT_CODE = 3
REPO = Path(__file__).resolve().parent.parent
# start.sh / start.bat restart the bot when it exits with RESTART_EXIT_CODE; anywhere else (a hosting
# panel running `python app.py`) the bot starts itself again instead
SUPERVISED = os.environ.get("CHUMAI_SUPERVISED") == "1"
started_at: str | None = None  # commit the running code came from (set by remember_start)


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


async def remember_start() -> None:
    """Note which commit is running, so a pull that happened without a restart is noticed later."""
    global started_at
    code, out = await _git("rev-parse", "--short", "HEAD")
    started_at = out if code == 0 else None


async def check() -> tuple[bool, str]:
    """Pull new commits. Returns (restart needed, message for the owner)."""
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
        if started_at and started_at != local:
            # the files were updated earlier but the bot never restarted onto them
            return True, f"최신 코드(`{local}`)는 받아져 있는데 봇은 `{started_at}` 로 돌고 있어요. 재시작할게요."
        return False, f"이미 최신 버전이에요. (`{branch}` @ `{local}`)"
    code, out = await _git("pull", "--ff-only")
    if code != 0 and "local changes" in out:
        if await _files_match("@{u}"):
            # the files are already the new version (copied in by the host, say), only git's record is
            # behind: move it along, nothing is lost
            code, out = await _git("reset", "--quiet", "@{u}")
        else:
            # files changed on the server (a host that copies some files in, say): put them aside in
            # `git stash` (`git stash list` / `git stash pop` brings them back), then update
            code, out = await _git("stash", "push", "--quiet", "-m", "chumai: changed files put aside before an update")
            if code == 0:
                log.warning("files changed in the bot folder were put aside (git stash) to update")
                code, out = await _git("pull", "--ff-only")
    if code != 0 and "untracked working tree files would be overwritten" in out:
        # new files of the update already there (a host copying files in): out of the way, then pull
        await _move_aside(_listed_paths(out))
        code, out = await _git("pull", "--ff-only")
    if code != 0:
        log.warning("git pull failed: %s", out)
        return False, (f"새 버전(`{remote}`)이 있지만 받지 못했어요. 지금 `{local}` 이에요.\n"
                       f"```{out[:900]}```\n봇 폴더에서 `git status` 로 바뀐 파일이 있는지 확인해 주세요.")
    log.info("updated %s -> %s", local, remote)
    return True, f"`{local}` → `{remote}` 로 업데이트했어요. 몇 초 뒤 재시작돼요."


def _listed_paths(out: str) -> list[str]:
    """The files git lists (tab-indented) in an error message."""
    return [line.strip() for line in out.splitlines() if line.startswith("\t") and line.strip()]


async def _move_aside(paths: list[str]) -> None:
    """Untracked files in the update's way: deleted if they're already the update's version, else
    renamed to <name>.bak (kept)."""
    for rel in paths:
        path = (REPO / rel).resolve()
        if REPO not in path.parents or not path.is_file():
            continue
        code, theirs = await _git("show", f"@{{u}}:{rel}")
        mine = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").strip()
        if code == 0 and mine == theirs.replace("\r\n", "\n").strip():
            path.unlink()
        else:
            path.rename(path.with_name(path.name + ".bak"))
            log.warning("untracked file %s was in the update's way; kept as %s.bak", rel, rel)


async def _files_match(ref: str) -> bool:
    """Whether the tracked files on disk are exactly `ref`'s."""
    # file permissions and line endings don't count: a host copying files in may change those
    code, _ = await _git("-c", "core.fileMode=false", "diff", "--quiet", "--ignore-cr-at-eol", ref, "--")
    return code == 0


async def pull_if_updated() -> bool:
    """Return True if new commits were pulled."""
    return (await check())[0]


async def version() -> str:
    code, out = await _git("log", "-1", "--format=%h %cd", "--date=format:%m/%d %H:%M")
    return out if code == 0 else "?"


def _requirements() -> bytes:
    try:
        return (REPO / "requirements.txt").read_bytes()
    except OSError:
        return b""


_requirements_at_start = _requirements()


def restart_in_place() -> None:
    """Start the bot again in this process (installing new requirements first, if they changed)."""
    import subprocess
    import sys

    if _requirements() != _requirements_at_start:
        log.info("requirements changed; installing")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(REPO / "requirements.txt")],
                       cwd=REPO, check=False)
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    if spec is not None and spec.name:  # python -m chumai
        args = ["-m", spec.name.removesuffix(".__main__")]
    else:  # python app.py
        args = sys.argv
    os.execv(sys.executable, [sys.executable, *args])
