import asyncio
import subprocess

from chumai import updater


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"], "HOME": str(cwd)}).stdout.decode()


def test_check_pulls_and_explains_failures(tmp_path, monkeypatch):
    origin, work, clone = tmp_path / "origin.git", tmp_path / "work", tmp_path / "clone"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    (work / "a.txt").write_text("1")
    _git(work, "add", ".")
    _git(work, "commit", "-qm", "one")
    _git(work, "push", "-q", "origin", "HEAD")
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    monkeypatch.setattr(updater, "REPO", clone)

    pulled, msg = asyncio.run(updater.check())
    assert not pulled and "이미 최신" in msg

    # files already up to date, but the running bot started from an older commit: restart
    monkeypatch.setattr(updater, "started_at", "0000000")
    restart, msg = asyncio.run(updater.check())
    assert restart and "재시작" in msg
    asyncio.run(updater.remember_start())
    assert not asyncio.run(updater.check())[0]

    (work / "a.txt").write_text("2")
    _git(work, "commit", "-qam", "two")
    _git(work, "push", "-q", "origin", "HEAD")
    (clone / "a.txt").write_text("edited locally")  # blocks a fast-forward pull: put aside, then pulled
    pulled, msg = asyncio.run(updater.check())
    assert pulled and "업데이트했어요" in msg and (clone / "a.txt").read_text() == "2"
    assert "put aside" in _git(clone, "stash", "list")
    assert asyncio.run(updater.version()) != "?"


def test_auto_update_restarts_the_bot(tmp_path, monkeypatch):
    import discord

    from chumai.bot import ChumaiBot
    from chumai.config import Config

    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite"))
    closed = []

    async def fake_close(self):
        await asyncio.sleep(0)  # let the loop's cancellation land, as the real close() does
        closed.append(True)

    async def pulled():
        return True

    monkeypatch.setattr(discord.Client, "close", fake_close)
    monkeypatch.setattr(updater, "pull_if_updated", pulled)

    async def main():
        bot = ChumaiBot(Config.from_env())
        bot.check_update.start()
        for _ in range(50):
            await asyncio.sleep(0.01)
            if closed:
                break
        return bot

    bot = asyncio.run(main())
    assert bot.restart_requested and closed == [True]


def test_restart_is_announced(tmp_path, monkeypatch):
    import asyncio

    from test_features_commands import _bot

    from chumai import bot as botmod

    bot = _bot(tmp_path, monkeypatch)
    sent, status = [], []

    class Channel:
        async def send(self, text):
            sent.append(text)

    async def presence(activity=None, **_):
        status.append(activity.name)

    bot.get_channel = lambda channel_id: Channel() if channel_id == 7 else None
    bot.change_presence = presence
    asyncio.run(bot.announce_restart())
    assert sent == [] and status == [botmod.RESTART_STATUS]  # no live log channel: the status only
    bot.links.set_setting(botmod.LIVE_LOG_SETTING, "7")
    asyncio.run(bot.announce_restart())
    assert sent == ["🔄 업데이트를 위해 봇이 재부팅됩니다. (약 1분 소요)"]
