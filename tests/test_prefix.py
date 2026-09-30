import asyncio
from types import SimpleNamespace

from chumai import prefix
from chumai import render
from test_features_commands import _bot, spy_renders


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
    calls = spy_renders(monkeypatch)
    bot = _bot(tmp_path, monkeypatch)
    r = _run(bot, "!info chuni aleph")
    assert r[-1][1]["file"].filename == render.filename("info_chunithm")
    assert calls[-1][1][1]["title"] == "Aleph-0"
    r = _run(bot, "!const chuni 14.7-14.9")
    assert calls[-1][1][4] == "2개"
    r = _run(bot, "!reach chunithm 14.7 16.7")
    assert calls[-1][1][2] == "1,007,500"
    r = _run(bot, '!info chuni "Easy Song"')
    assert calls[-1][1][1]["title"] == "Easy Song"


def test_short_aliases(tmp_path, monkeypatch):
    calls = spy_renders(monkeypatch)
    bot = _bot(tmp_path, monkeypatch)
    _run(bot, "!i c aleph")
    assert calls[-1][0] == "render_song"
    _run(bot, "!c c 14.7-14.9")
    assert calls[-1][0] == "render_chart_list"
    _run(bot, "!rh c 14.7 16.7")
    assert calls[-1][1][2] == "1,007,500"
    _run(bot, "!cal m 13.5 100.5")
    assert calls[-1][0] == "render_scores"
    r = _run(bot, "!h")
    assert "`!b`" in r[-1][1]["embed"].fields[1].value


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
    calls = spy_renders(monkeypatch)
    _run(bot, "!const chuni 14+")
    assert calls[-1][1][2] == "14+ (14.5~14.9)"


def test_r_alias(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    r = _run(bot, "!r chuni 14+ 2")
    assert r[-1][1]["file"].filename == render.filename("random_chunithm")


def test_give_up_aliases(tmp_path, monkeypatch):
    bot = _bot(tmp_path, monkeypatch)
    assert "진행 중인 게임이 없어요" in _run(bot, "!포기")[-1][0]
    assert "진행 중인 게임이 없어요" in _run(bot, "!gu")[-1][0]


def test_korean_command_names(tmp_path, monkeypatch):
    calls = spy_renders(monkeypatch)
    bot = _bot(tmp_path, monkeypatch)
    _run(bot, "!곡정보 츄니 aleph")
    assert calls[-1][0] == "render_song"
    _run(bot, "!상수표 츄니 14.7-14.9")
    assert calls[-1][0] == "render_chart_list"
    r = _run(bot, "!플레이로그")
    assert "`!플레이로그 <켜기 / 끄기 / 테스트 / 전체>`" in r[-1][0]
    r = _run(bot, "!랜덤 마이")
    assert "사용법: `!랜덤 <game> <level> [count]`" in r[-1][0]
    r = _run(bot, "!별명 목록 츄니")
    assert "`!별명 목록" in r[-1][0]
