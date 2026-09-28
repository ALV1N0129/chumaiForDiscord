import asyncio
from types import SimpleNamespace

from chumai import prefix
from test_features_commands import _bot


class FakeChannel:
    id = 5

    async def typing(self):
        pass


class FakeMessage:
    def __init__(self, content, mentions=()):
        self.content = content
        self.author = SimpleNamespace(id=1, bot=False, mention="@p")
        self.channel = FakeChannel()
        self.guild = None
        self.mentions = list(mentions)
        self.replies = []

    async def reply(self, content=None, **kw):
        self.replies.append((content, kw))


def _run(bot, text, mentions=()):
    msg = FakeMessage(text, mentions)
    asyncio.run(prefix.handle(bot, msg, "!"))
    return msg.replies


def test_prefix_commands(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    r = _run(bot, "!info chuni aleph")
    assert r[-1][1]["embed"].title == "Aleph-0"
    r = _run(bot, "!const c 14.7-14.9")
    assert "(2개)" in r[-1][1]["embed"].title
    r = _run(bot, "!reach chunithm 14.7 16.7")
    assert "1,007,500" in r[-1][0]
    r = _run(bot, '!info chuni "Easy Song"')
    assert r[-1][1]["embed"].title == "Easy Song"


def test_prefix_errors_and_special_cases(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    r = _run(bot, "!random mai")
    assert "level" in r[-1][0] and "사용법" in r[-1][0]
    r = _run(bot, "!reach pump 14 16")
    assert "maimai / chunithm" in r[-1][0]
    r = _run(bot, "!playlog")
    assert "on / off / test" in r[-1][0]
    r = _run(bot, "!login")
    assert isinstance(r[-1][1]["view"], prefix.LoginView)
    assert _run(bot, "!nosuchcommand") == []


def test_greedy_song_then_difficulty(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    cmd = bot.tree.get_command("whatif")
    kw = prefix.parse_args(cmd, ["chuni", "aleph", "zero", "MAS", "1009000"], FakeMessage(""))
    assert kw == {"game": "chunithm", "song": "aleph zero", "difficulty": "MAS", "score": 1009000.0}


def test_prefix_level_and_count(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    cmd = bot.tree.get_command("random")
    assert prefix.parse_args(cmd, ["chuni", "14+", "3"], FakeMessage("")) == {
        "game": "chunithm", "level": "14+", "count": 3}
    assert prefix.parse_args(cmd, ["chuni", "14.0-14.8"], FakeMessage("")) == {
        "game": "chunithm", "level": "14.0-14.8"}
    r = _run(bot, "!const chuni 14+")
    assert "14.5~14.9" in r[-1][1]["embed"].title


def test_r_alias(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    r = _run(bot, "!r chuni 14+ 2")
    assert r[-1][1]["file"].filename == "random_chunithm.png"
