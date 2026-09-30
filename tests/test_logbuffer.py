import logging
import re
from pathlib import Path

from chumai import logbuffer
from chumai.logbuffer import RecentLogs


def _logged(buf, name, level, msg, *args, exc=None):
    logger = logging.getLogger(name)
    logger.addHandler(buf)
    logger.setLevel(logging.INFO)
    try:
        if exc is None:
            logger.log(level, msg, *args)
        else:
            try:
                raise exc
            except type(exc):
                logger.log(level, msg, *args, exc_info=True)
    finally:
        logger.removeHandler(buf)


def test_summed_up_in_korean():
    buf = RecentLogs(size=10)
    _logged(buf, "chumai.bot", logging.INFO, "synced %d global commands (GUILD_ID not set; may take a while to "
            "show up): %s", 25, "b50, today")
    _logged(buf, "chumai.bot", logging.INFO, "song database loaded: %d CHUNITHM charts, %d maimai charts", 1, 2)
    _logged(buf, "discord.gateway", logging.INFO, "Shard ID None has connected to Gateway")
    _logged(buf, "chumai.bot", logging.ERROR, "failed to fetch %s data from SEGA NET", "chunithm",
            exc=TimeoutError())
    _logged(buf, "chumai.bot", logging.ERROR, "play log check failed for %s/%s", 42, "maimai",
            exc=ValueError("bad page"))
    _logged(buf, "discord.gateway", logging.WARNING, "Shard ID %s heartbeat blocked for more than %s seconds.",
            None, 20)
    _logged(buf, "chumai.somewhere", logging.WARNING, "something new went wrong")
    lines = buf.tail(10)
    assert len(lines) == 5  # the routine lines are left out
    assert lines[0].endswith("재부팅 되었어요.") and lines[0].startswith("✅")
    assert lines[1].startswith("❌") and lines[1].endswith(
        "SEGA NET에서 CHUNITHM 정보를 불러오지 못했어요. (원인: 응답 시간 초과)")
    assert lines[2].endswith("<@42> 님의 maimai 플레이 기록을 불러오지 못했어요. (원인: ValueError)")
    assert "봇이 잠시 멈췄어요" in lines[3]
    assert lines[4].startswith("⚠️") and lines[4].endswith("알 수 없는 문제가 생겼어요.")
    assert "Traceback" not in "\n".join(lines)
    # the live channel gets the same lines
    assert buf.take().split("\n") == lines


def test_every_logged_message_has_a_summary():
    source = Path(logbuffer.__file__).parent
    call = re.compile(r'log(?:ging\.getLogger\([^)]*\))?\.(?:info|warning|error|exception)\(\s*"([^"]*)"')
    missing = []
    for path in source.glob("*.py"):
        for template in call.findall(path.read_text(encoding="utf-8")):
            korean = any("가" <= ch <= "힣" for ch in template)
            if template not in logbuffer.SUMMARIES and not korean:
                missing.append(f"{path.name}: {template}")
    assert missing == []


def test_repeats_counted_and_reconnect_noted():
    buf = RecentLogs(size=10)
    for _ in range(4):
        _logged(buf, "discord.client", logging.ERROR, "Attempting a reconnect", exc=OSError("dns"))
    _logged(buf, "discord.gateway", logging.INFO, "Shard ID %s has successfully RESUMED session %s.", None, "x")
    _logged(buf, "discord.gateway", logging.INFO, "Shard ID %s has successfully RESUMED session %s.", None, "y")
    _logged(buf, "chumai.bot", logging.INFO, "song database updated")
    _logged(buf, "chumai.bot", logging.INFO, "song database updated")
    lines = buf.tail(10)
    assert len(lines) == 3
    assert lines[0].endswith("디스코드 연결에 문제가 생겼어요. (원인: OSError) ×4")
    assert lines[1].endswith("디스코드에 다시 연결됐어요.")  # once, not for every resume
    assert lines[2].endswith("곡 데이터를 업데이트했어요. ×2")
    assert buf.take().split("\n") == lines[1:]  # discord.py's own errors stay off the live channel
