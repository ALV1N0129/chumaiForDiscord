"""Call the slash command handlers with a fake interaction."""

import asyncio
from types import SimpleNamespace

from PIL import Image

from chumai import features, render
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


def spy_renders(monkeypatch):
    """Record the arguments of every render_* call (the real renderer still runs)."""
    calls = []
    for name in ("render_song", "render_chart_list", "render_scores", "render_random"):
        real = getattr(render, name)

        def wrapped(*a, _real=real, _name=name, **k):
            calls.append((_name, a, k))
            return _real(*a, **k)

        monkeypatch.setattr(render, name, wrapped)
    return calls


def _call(bot, name, **kw):
    log = []
    interaction = _interaction(log, **kw)
    interaction.client = bot
    asyncio.run(bot.tree.get_command(name).callback(interaction, **kw))
    return log


def test_info_const_reach_random(tmp_path, monkeypatch):
    calls = spy_renders(monkeypatch)
    bot = _bot(tmp_path, monkeypatch)
    log = _call(bot, "info", game="chunithm", song="aleph")
    assert log[-1][2]["file"].filename == render.filename("info_chunithm")
    _, (game, song, charts, jacket), _ = calls[-1]
    assert song["title"] == "Aleph-0" and any(c["const"] == 14.9 for c in charts) and jacket

    log = _call(bot, "const", game="chunithm", level="14.7-14.9")
    assert log[-1][2]["file"].filename == render.filename("const_chunithm")
    _, (game, kicker, title, rows, sub, *_), _ = calls[-1]
    assert title == "14.7~14.9" and sub == "2개" and len(rows) == 2

    log = _call(bot, "reach", game="chunithm", const=14.7, target=16.7)
    assert calls[-1][1][2] == "1,007,500"
    assert log[-1][2]["file"].filename == render.filename("reach_chunithm")

    log = _call(bot, "random", game="chunithm", level="12-15", count=2)
    assert log[-1][2]["file"].filename == render.filename("random_chunithm")
    assert len(calls[-1][1][1]) == 2

    log = _call(bot, "calc", game="chunithm", const=14.7, score=1_007_500.0)
    assert log[-1][2]["file"].filename == render.filename("calc_chunithm")
    assert calls[-1][1][2] == "16.70"

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

        async def post(self, path, data):
            FakeNet.posted.append(path)
            return (fix / "best30.html").read_bytes()  # same list format as the record pages

    FakeNet.posted = []

    monkeypatch.setattr(botmod, "NetClient", FakeNet)
    monkeypatch.setattr(features, "NetClient", FakeNet)
    bot = _bot(tmp_path, monkeypatch)
    bot.links.set_sega_token(1, "tok")

    shown = []
    real_credit = botmod.render_credit

    def spy_credit(game, player, entries, badges, *rest):
        shown.append([(e.title, b and b.kind, b and b.best) for e, b in zip(entries, badges)])
        return real_credit(game, player, entries, badges, *rest)

    monkeypatch.setattr(botmod, "render_credit", spy_credit)
    log = _call(bot, "recent", game="chunithm")
    assert log[-1][2]["file"].filename == render.filename("recent_chunithm")
    # no saved scores yet: new records without the improvement, and the record pages are saved
    assert [kind for _, kind, _ in shown[-1]] == ["new"] * 4
    assert len(FakeNet.posted) == 5 and bot.links.get_bests(1, "chunithm")[1] == "2023/08/04 18:33#04"

    images, _ = asyncio.run(botmod.render_credits(
        bot, 1, "chunithm", lambda rs: [r for r in rs if r.date.startswith("2023/08/04 15")]))
    aleph = next(x for x in shown[-1] if x[0] == "Aleph-0")
    assert aleph[1] == "best" and aleph[2] == bot.links.get_bests(1, "chunithm")[0][("Aleph-0", "MASTER")]

    log = _call(bot, "profile", game="chunithm", member=None)
    assert log[-1][2]["file"].filename == render.filename("profile_chunithm")


def test_whatif_and_recommend(tmp_path, monkeypatch):
    from chumai import bot as botmod
    from chumai.b50 import make_entry, select_b50

    entries = [make_entry("chunithm", f"S{i}", "MASTER", "14", 14.0, 1_009_000, None, False) for i in range(30)]
    entries += [make_entry("chunithm", f"N{i}", "MASTER", "13+", 13.5, 1_007_500, None, True) for i in range(20)]
    b50 = select_b50("chunithm", "p", entries)

    async def fake_b50(bot, game, discord_id, token, images=True):
        return b50

    monkeypatch.setattr(botmod, "sega_b50", fake_b50)
    calls = spy_renders(monkeypatch)
    bot = _bot(tmp_path, monkeypatch)
    bot.links.set_sega_token(1, "tok")

    log = _call(bot, "whatif", game="chunithm", song="aleph", difficulty="MAS", score=1_009_000.0)
    assert log[-1][2]["file"].filename == render.filename("whatif_chunithm")
    _, (game, kicker, headline, detail, rows, chart), _ = calls[-1]
    assert "»" in headline and "+" in detail and chart["title"] == "Aleph-0"
    assert [r for r in rows if r[3]] == [("1,009,000", "SSS+", "17.05", True)]

    log = _call(bot, "recommend", game="chunithm")
    assert log[-1][2]["file"].filename == render.filename("recommend_chunithm")
    rows, sub = calls[-1][1][3], calls[-1][1][4]
    assert rows and all(r["right"].startswith("+") and r["sub_line"].startswith("목표 S") for r in rows)
    assert "현재 15.89" in sub and "13+ SSS" in sub  # the roadmap's advice for 15.25~16.00


def test_sega_b50_loads_pages_once_for_recommend(tmp_path, monkeypatch):
    from pathlib import Path

    from chumai import bot as botmod

    fix = Path(__file__).parent / "fixtures" / "chunithm_net"
    requested = []

    class FakeNet:
        pages = {
            "/mobile/home/playerData/": (fix / "player_data.html").read_bytes(),
            "/mobile/home/playerData/ratingDetailBest/": (fix / "best30.html").read_bytes(),
            "/mobile/home/playerData/ratingDetailRecent/": (fix / "recent10.html").read_bytes(),
        }

        def __init__(self, game, clal):
            self.clal = clal

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, path):
            requested.append(path)
            return self.pages[path]

        async def get_bytes(self, url):
            requested.append(url)
            return None

    monkeypatch.setattr(botmod, "NetClient", FakeNet)
    bot = _bot(tmp_path, monkeypatch)
    first = asyncio.run(botmod.sega_b50(bot, "chunithm", 1, "tok", images=False))
    again = asyncio.run(botmod.sega_b50(bot, "chunithm", 1, "tok", images=False))
    assert first is again and len(first.old) == 30
    assert len(requested) == 3  # no nameplate / icon pages, and the second call used the cache
