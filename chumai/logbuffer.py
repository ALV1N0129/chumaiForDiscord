"""The bot's log, summed up in short Korean lines for the bot's owner: /logs status shows the latest,
/logs live posts them to a channel as they happen. The full log (English, with tracebacks) stays in
the host's console.

Each message the bot logs has its summary in SUMMARIES, by the message's template; routine
messages have None and are left out. A warning or error without a summary still shows, as
"알 수 없는 문제" with its cause."""

from __future__ import annotations

import datetime
import logging
import re
from collections import deque

KST = datetime.timezone(datetime.timedelta(hours=9))
GAMES = {"chunithm": "CHUNITHM", "maimai": "maimai"}


def _game(game) -> str:
    return GAMES.get(str(game), str(game))


# git's errors -> what they mean, in a few words
GIT_REASONS = [
    ("local changes", "봇 폴더에서 바뀐 파일이 있어요. `git status` 로 확인해 주세요"),
    ("untracked working tree files would be overwritten", "봇 폴더에 덮어쓸 수 없는 파일이 있어요"),
    ("not possible to fast-forward", "봇 폴더의 코드가 GitHub와 갈라졌어요"),
    ("diverg", "봇 폴더의 코드가 GitHub와 갈라졌어요"),
    ("could not resolve host", "GitHub에 접속하지 못했어요"),
    ("unable to access", "GitHub에 접속하지 못했어요"),
    ("timed out", "시간 초과"),
    ("index.lock", "다른 git 작업이 남아 있어요 (.git/index.lock)"),
]


def _git_reason(out) -> str:
    text = str(out)
    for key, reason in GIT_REASONS:
        if key in text.lower():
            return reason
    line = next((ln for ln in text.splitlines() if ln.strip()), "?")
    return re.sub(r"//[^/@\s]+@", "//", line)[:120]  # no login in a URL


# message template -> summary: text, a function of the message's arguments, or None (not shown)
SUMMARIES = {
    # start, updates
    "synced %d commands to server %s: %s": "재부팅 되었어요.",
    "synced %d global commands (GUILD_ID not set; may take a while to show up): %s": "재부팅 되었어요.",
    "new version pulled; restarting": None,  # the bot says so itself (RESTART_NOTICE)
    "updated %s -> %s": lambda old, new, *_: f"업데이트했어요. ({str(old)[:7]} → {str(new)[:7]})",
    "git fetch failed: %s": lambda out, *_: f"업데이트를 확인하지 못했어요. ({_git_reason(out)})",
    "git pull failed: %s": lambda out, *_: f"업데이트를 받지 못했어요. ({_git_reason(out)})",
    "update failed": "업데이트에 실패했어요.",
    "untracked file %s was in the update's way; kept as %s.bak":
        lambda path, *_: f"업데이트와 겹치는 파일 `{path}` 을(를) `{path}.bak` 으로 바꿔 두고 업데이트했어요.",
    "files changed in the bot folder were put aside (git stash) to update":
        "봇 폴더에서 바뀐 파일을 따로 보관(git stash)하고 업데이트했어요.",
    "live logs on in channel %s": "실시간 로그를 켰어요.",
    # play logs
    "posted %d credit(s) for %s/%s": lambda n, who, game: f"<@{who}> 님의 {_game(game)} 플레이 기록 {n}크레딧을 올렸어요.",
    "play log check failed for %s/%s": lambda who, game: f"<@{who}> 님의 {_game(game)} 플레이 기록을 불러오지 못했어요.",
    "play log check for %s/%s works again": lambda who, game: f"<@{who}> 님의 {_game(game)} 플레이 기록을 다시 불러올 수 있어요.",
    "no permission to post play logs in channel %s (%s)":
        lambda channel, missing: f"<#{channel}> 채널에 플레이 기록을 올릴 권한이 없어요. ({missing})",
    "play log test failed": "플레이 기록 테스트에 실패했어요.",
    "best scores saved for %s: %s": lambda who, games: (
        f"<@{who}> 님이 로그인해서 곡별 최고 점수를 저장했어요. ({', '.join(_game(g) for g in str(games).split(', '))})"),
    "play log for everyone on in channel %s": lambda channel: f"로그인한 사람 모두의 플레이 기록을 <#{channel}> 에 올려요.",
    "play log for everyone off": "전체 플레이 기록 업로드를 껐어요.",
    "auto play log started for %s/%s": lambda who, game: f"<@{who}> 님의 {_game(game)} 플레이 기록도 올리기 시작했어요.",
    "auto play log for %s/%s left out after %d failed tries":
        lambda who, game, n: f"<@{who}> 님의 {_game(game)} 기록을 불러오지 못해서 전체 업로드에서 뺐어요. (안 하는 게임?)",
    # SEGA
    "failed to fetch %s data from SEGA NET": lambda game: f"SEGA NET에서 {_game(game)} 정보를 불러오지 못했어요.",
    "SEGA ID login failed": "SEGA ID 로그인에 실패했어요.",
    "login refused: status=%s location=%s%s": "SEGA ID 로그인이 거절됐어요. (아이디·비밀번호가 틀렸거나 잠시 막힘)",
    "login ok but no clal: status=%s location_host=%s set-cookie=%s jar=%s": "SEGA ID 로그인 후 인증 정보를 받지 못했어요.",
    "could not load profile image %s": "프로필 이미지를 불러오지 못했어요.",
    "could not load CHUNITHM nameplate": "CHUNITHM 네임플레이트를 불러오지 못했어요.",
    "nameplate failed": "네임플레이트를 불러오지 못했어요.",
    "could not load CHUNITHM lamps": "CHUNITHM 램프(AJ·FC) 정보를 불러오지 못했어요.",
    "could not load the CHUNITHM song list": "CHUNITHM 곡 목록을 불러오지 못했어요.",
    "CHUNITHM record pages failed; using the rating lists": "CHUNITHM 기록 페이지를 불러오지 못해서 레이팅 목록으로 대신했어요.",
    "could not load best scores": "최고 점수를 불러오지 못했어요.",
    "could not load the %s record page": lambda page: f"{page} 기록 페이지를 불러오지 못했어요. (나머지는 저장했어요)",
    # stored data
    "TOKEN_ENCRYPTION_KEY is not set; SEGA login tokens are stored unencrypted":
        "로그인 정보 암호화 키(TOKEN_ENCRYPTION_KEY)가 설정되지 않았어요.",
    "could not decrypt SEGA token for %s (key changed?)":
        lambda who: f"<@{who}> 님의 저장된 로그인 정보를 풀지 못했어요. (암호화 키가 바뀌었나요?)",
    # songs, jackets, charts
    "song database updated": "곡 데이터를 업데이트했어요.",
    "failed to download song database; using cached copy if any": "곡 데이터를 받지 못했어요. 저장된 걸 쓸게요.",
    "song database is unavailable; chart constants will be estimated": "곡 데이터가 없어서 보면 상수를 추정해요.",
    "song database loaded: %d CHUNITHM charts, %d maimai charts": None,
    "jacket index loaded: %d CHUNITHM, %d maimai": None,
    "could not download %s; jackets may be missing": "자켓 목록을 받지 못했어요.",
    "%s did not return JSON": "자켓 목록을 받지 못했어요.",
    "jacket %s: download failed (%s); retrying in %d min": "자켓을 받지 못했어요. 잠시 뒤에 다시 받을게요.",
    "jacket fetch failed": "자켓을 불러오지 못했어요.",
    "failed to fetch jackets": "자켓을 불러오지 못했어요.",
    "saved %d uploaded jackets": lambda n, *_: f"PC에서 보낸 자켓 {n}개를 저장했어요.",
    "could not save uploaded jackets %s": "PC에서 보낸 자켓을 저장하지 못했어요.",
    "chuni-penguin nicknames updated": None,
    "failed to download chuni-penguin nicknames; using cached copy if any": "커뮤니티 곡 별명을 받지 못했어요. 저장된 걸 쓸게요.",
    "could not load chuni-penguin nicknames": "커뮤니티 곡 별명을 받지 못했어요.",
    # fonts, logos, certificates
    "downloading the Korean/Japanese font (about 17MB, first run only)...": "한글·일본어 폰트를 받고 있어요. (처음 한 번만)",
    "font saved to %s": None,
    "could not download the font; Korean text may not show correctly": "폰트를 받지 못했어요. 한글이 깨질 수 있어요.",
    "downloaded %s logo": None,
    "could not download the %s logo from %s (PNG/JPG/WebP only)": lambda game, *_: f"{_game(game)} 로고를 받지 못했어요.",
    "added missing intermediate certificate for %s: %s": None,
    "could not fetch the missing intermediate certificate for %s": lambda host: f"{host} 인증서 문제로 접속하지 못했어요.",
    # commands
    "prefix command %s failed": lambda name: f"`!{name}` 명령어를 처리하다 오류가 났어요.",
    "could not send logs to channel %s: %s": "실시간 로그를 채널에 올리지 못했어요.",
}

# discord.py's own messages worth a line (by a part of the text); its other chatter is left out
LIBRARY = [
    ("heartbeat blocked", "봇이 잠시 멈췄어요. (무거운 작업 중이거나 메모리가 부족해요)"),
    ("rate limited", "디스코드 요청 제한에 걸려서 잠시 기다려요."),
    ("Ignoring exception in command", "명령어를 처리하다 오류가 났어요."),
    ("Ignoring exception", "처리하다 오류가 났어요."),
]


def _cause(exc: BaseException) -> str:
    """The cause of an error in a few Korean words."""
    import asyncio

    name = type(exc).__name__
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "응답 시간 초과"
    if isinstance(exc, MemoryError):
        return "메모리 부족"
    if name in ("ClientConnectorError", "ServerDisconnectedError", "ClientOSError", "ConnectionResetError"):
        return "접속 실패"
    if name == "ClientResponseError":
        return f"서버 응답 {getattr(exc, 'status', '?')}"
    if name in ("SegaError", "LoginFailed", "SessionExpired") and str(exc):
        return str(exc)
    if name == "Forbidden":
        return "권한 없음"
    return name


def summarize(record: logging.LogRecord) -> str | None:
    """The Korean line for a log record, or None to leave it out."""
    template = record.msg if isinstance(record.msg, str) else str(record.msg)
    text: str | None
    if template in SUMMARIES:
        found = SUMMARIES[template]
        try:
            text = found(*(record.args or ())) if callable(found) else found
        except Exception:
            text = None if found is None else "알 수 없는 문제가 생겼어요."
        if text is None:
            return None
    elif record.name.startswith("discord"):
        message = record.getMessage()
        text = next((t for key, t in LIBRARY if key in message), None)
        if text is None:
            if record.levelno < logging.ERROR:
                return None
            text = "디스코드 연결에 문제가 생겼어요."
    elif any("가" <= ch <= "힣" for ch in template):  # already in Korean
        text = record.getMessage()
    elif record.levelno >= logging.WARNING:
        text = "알 수 없는 문제가 생겼어요."
    else:
        return None
    exc = record.exc_info[1] if record.exc_info else None
    if exc is not None:
        text += f" (원인: {_cause(exc)})"
    mark = "❌" if record.levelno >= logging.ERROR else "⚠️" if record.levelno >= logging.WARNING else "✅"
    return _line(record, mark, text)


def _line(record: logging.LogRecord, mark: str, text: str) -> str:
    when = datetime.datetime.fromtimestamp(record.created, KST).strftime("%m/%d %H:%M")
    return f"{mark} `{when}` {text}"


REPEAT_SECONDS = 60  # the same line again within this: counted on the first one (×N)
RECONNECTED = ("has connected to Gateway", "has successfully RESUMED")


class RecentLogs(logging.Handler):
    def __init__(self, size: int = 200):
        super().__init__(logging.INFO)
        self.lines: deque[str] = deque(maxlen=size)
        # lines not yet sent to the live log channel; failures to send them are not sent, so they
        # can't feed themselves
        self.pending: deque[str] = deque(maxlen=500)

        self._discord_down = False  # a connection error seen, not yet connected again
        self._last: tuple[str, float, int, str] | None = None  # (line without time, when, count, line)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = summarize(record)
        except Exception:
            self.handleError(record)
            return
        library = record.name.startswith("discord")
        # not a failure to send the live log itself, nor discord.py's own (it may be about sending)
        live = not record.name.startswith(("chumai.live", "discord")) or "heartbeat" in str(record.msg)
        if library and line is not None and record.levelno >= logging.ERROR:
            self._discord_down = True
        elif library and self._discord_down and any(key in str(record.msg) for key in RECONNECTED):
            self._discord_down = False
            line, live = _line(record, "✅", "디스코드에 다시 연결됐어요."), True
        if line is None:
            return
        line = line[:400]
        same = line.split("` ", 1)[-1] + line[:2]
        last = self._last
        if last and last[0] == same and record.created - last[1] < REPEAT_SECONDS:
            count = last[2] + 1
            counted = f"{last[3]} ×{count}"
            for lines in (self.lines, self.pending):  # the line already there, unless it went out
                if lines and lines[-1].startswith(last[3]):
                    lines[-1] = counted
            self._last = (same, last[1], count, last[3])
            return
        self._last = (same, record.created, 1, line)
        self.lines.append(line)
        if live:
            self.pending.append(line)

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
