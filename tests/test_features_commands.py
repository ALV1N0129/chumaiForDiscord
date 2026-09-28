"""Call the slash command handlers with a fake interaction."""

import asyncio
from types import SimpleNamespace

from PIL import Image

from chumai import features
from chumai.bot import ChumaiBot
from chumai.config import Config

from test_tools import SEEDS


class FakeResponse:
    def __init__(self, log):
        self.log = log

    async def send_message(self, content=None, **kw):
        self.log.append(("send", content, kw))

    async def defer(self, **kw):
        self.log.append(("defer", None, kw))


class FakeFollowup:
    def __init__(self, log):
        self.log = log

    async def send(self, content=None, **kw):
        self.log.append(("followup", content, kw))


def _interaction(log, **ns):
    return SimpleNamespace(
        response=FakeResponse(log), followup=FakeFollowup(log), channel_id=5,
        user=SimpleNamespace(id=1, mention="@p"), namespace=SimpleNamespace(**ns), client=None,
    )


def _bot(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite"))
    bot = ChumaiBot(Config.from_env())
    bot.songdb.load(SEEDS)
    jacket = tmp_path / "jacket.png"
    Image.new("RGB", (200, 200), (0, 128, 255)).save(jacket)

    async def fetch(game, keys):
        return {i: jacket for i in range(len(keys))}

    bot.jackets.fetch = fetch
    return bot


def _call(bot, name, **kw):
    log = []
    interaction = _interaction(log, **kw)
    interaction.client = bot
    asyncio.run(bot.tree.get_command(name).callback(interaction, **kw))
    return log


def test_info_const_reach_random(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    log = _call(bot, "info", game="chunithm", song="aleph")
    embed = log[-1][2]["embed"]
    assert embed.title == "Aleph-0" and "14.9" in embed.fields[0].value

    log = _call(bot, "const", game="chunithm", level="14.7-14.9")
    assert "(2개)" in log[-1][2]["embed"].title

    log = _call(bot, "reach", game="chunithm", const=14.7, target=16.7)
    assert "1,007,500" in log[-1][1]

    log = _call(bot, "random", game="chunithm", level="12-15", count=2)
    embeds = log[-1][2]["embeds"]
    assert len(embeds) == 2 and len(log[-1][2]["files"]) == 2
    assert {e.fields[1].name for e in embeds} <= {"MASTER", "EXPERT"}
    assert embeds[0].thumbnail.url.startswith("attachment://jacket")

    log = _call(bot, "info", game="chunithm", song="zzzzzz no such song")
    assert "찾지 못했어요" in log[-1][1]


def test_guess_and_answer(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    monkeypatch.setattr(features, "GUESS_SECONDS", 3600)

    async def run():
        log = []
        i = _interaction(log)
        i.client = bot
        await bot.tree.get_command("guess").callback(i, game="chunithm", level=None)
        assert "이 자켓의 곡은?" in log[-1][1]
        # find which song was picked by trying every title
        for title in ["Aleph-0", "AXION", "Easy Song"]:
            alog = []
            a = _interaction(alog)
            a.client = bot
            await bot.tree.get_command("answer").callback(a, title=title)
            if "정답" in (alog[-1][1] or ""):
                return True
        return False

    assert asyncio.run(run())


def test_recent_and_profile_with_fake_sega(tmp_path, monkeypatch):
    from pathlib import Path

    from chumai import bot as botmod

    fix = Path(__file__).parent / "fixtures" / "chunithm_net"

    class FakeNet:
        pages = {
            "/mobile/record/playlog": (fix / "playlog.html").read_bytes(),
            "/mobile/home/playerData/": (fix / "player_data.html").read_bytes(),
            "/mobile/collection/customise/": (fix / "collection_customise.html").read_bytes(),
        }

        def __init__(self, game, clal):
            self.clal = clal

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, path):
            return self.pages[path]

        async def get_bytes(self, url):
            raise botmod.SegaError("no images")

    monkeypatch.setattr(botmod, "NetClient", FakeNet)
    monkeypatch.setattr(features, "NetClient", FakeNet)
    bot = _bot(tmp_path, monkeypatch)
    bot.links.set_sega_token(1, "tok")

    log = _call(bot, "recent", game="chunithm")
    assert log[-1][2]["file"].filename == "recent_chunithm.png"

    log = _call(bot, "profile", game="chunithm", member=None)
    assert log[-1][2]["file"].filename == "profile_chunithm.png"


def test_whatif_and_recommend(tmp_path, monkeypatch):
    from chumai import bot as botmod
    from chumai.b50 import make_entry, select_b50

    entries = [make_entry("chunithm", f"S{i}", "MASTER", "14", 14.0, 1_000_000, None, False) for i in range(30)]
    entries += [make_entry("chunithm", f"N{i}", "MASTER", "14", 13.5, 1_000_000, None, True) for i in range(20)]
    b50 = select_b50("chunithm", "p", entries)

    async def fake_b50(bot, game, discord_id, token):
        return b50

    monkeypatch.setattr(botmod, "sega_b50", fake_b50)
    bot = _bot(tmp_path, monkeypatch)
    bot.links.set_sega_token(1, "tok")

    log = _call(bot, "whatif", game="chunithm", song="aleph", difficulty="MAS", score=1_009_000.0)
    assert "→" in log[-1][1] and "+" in log[-1][1]

    log = _call(bot, "recommend", game="chunithm")
    assert "Aleph-0" in log[-1][2]["embed"].description
