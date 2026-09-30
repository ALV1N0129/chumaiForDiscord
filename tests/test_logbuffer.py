import logging

from chumai.logbuffer import RecentLogs


def test_keeps_own_messages_and_warnings_shortening_exceptions():
    buf = RecentLogs(size=3)
    ours, lib = logging.getLogger("chumai.test"), logging.getLogger("discord.gateway")
    for logger in (ours, lib):
        logger.addHandler(buf)
        logger.setLevel(logging.INFO)
    try:
        lib.info("heartbeat")  # a library's INFO chatter isn't kept
        ours.info("community nicknames: 3")
        lib.warning("rate limited")
        try:
            raise ValueError("bad page")
        except ValueError:
            ours.exception("play log check failed for 1/chunithm")
        lines = buf.tail(10)
    finally:
        for logger in (ours, lib):
            logger.removeHandler(buf)
    assert len(lines) == 3 and not any("heartbeat" in line for line in lines)
    assert lines[-1].endswith("play log check failed for 1/chunithm [ValueError: bad page]")
    assert "Traceback" not in "\n".join(lines)
