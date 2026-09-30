import asyncio
from pathlib import Path
from types import SimpleNamespace

from chumai import bot as botmod
from chumai import net_parsers
from chumai.songdb import SongDB
from chumai.storage import LinkStore

FIX = Path(__file__).parent / "fixtures" / "chunithm_net"

MAIMAI_ROW = """
<div class="p_10 t_l f_0 v_b">
  <div class="playlog_top_container"><div class="sub_title t_c f_r f_11">
    <span class="red f_b v_b">TRACK 0{track}</span><span class="v_b">2026/09/27 1{track}:00</span></div>
    <img src="https://maimaidx-eng.com/maimai-mobile/img/diff_master.png" class="playlog_diff v_b"></div>
  <div class="playlog_master_container">
    <div class="basic_block m_5 p_5 p_l_10 f_13 break">
      <img src="https://maimaidx-eng.com/maimai-mobile/img/playlog/clear.png" class="w_80 f_r">天体観測</div>
    <img src="https://maimaidx-eng.com/maimai-mobile/img/Music/abc.png" class="music_img m_5 f_l">
    <img src="https://maimaidx-eng.com/maimai-mobile/img/music_dx.png" class="playlog_music_kind_icon">
    <img src="https://maimaidx-eng.com/maimai-mobile/img/playlog/sssplus.png?ver=1" class="playlog_scorerank">
    <div class="playlog_achievement_txt t_r">100<span class="f_20">.5123%</span></div>
    <img src="https://maimaidx-eng.com/maimai-mobile/img/playlog/newrecord.png" class="playlog_achievement_newrecord">
    <div class="playlog_result_innerblock">
      <img src="https://maimaidx-eng.com/maimai-mobile/img/playlog/applus.png?ver=1">
      <img src="https://maimaidx-eng.com/maimai-mobile/img/playlog/fs_dummy.png"></div>
  </div>
</div>"""


def test_chunithm_playlog_and_credits():
    records = net_parsers.parse_chunithm_playlog((FIX / "playlog.html").read_bytes())
    assert len(records) == 50
    top = records[0]
    assert (top.title, top.difficulty, top.score, top.track, top.new_record) == ("Air", "MASTER", 950_592, 4, True)
    credits = net_parsers.group_credits(records)
    assert all(c[0].track <= c[-1].track for c in credits)
    assert [r.track for r in credits[-1]] == [1, 2, 3, 4]


def test_maimai_playlog():
    html = '<div class="main_wrapper">' + MAIMAI_ROW.format(track=2) + MAIMAI_ROW.format(track=1) + "</div>"
    records = net_parsers.parse_maimai_playlog(html)
    assert len(records) == 2
    r = records[0]
    assert (r.title, r.difficulty, r.score, r.rank, r.lamp, r.new_record, r.track) == (
        "天体観測", "DX Master", 100.5123, "SSS+", "AP+", True, 2)
    assert r.jacket_url.endswith("/Music/abc.png")
    assert [len(c) for c in net_parsers.group_credits(records)] == [2]


def test_unrated_plays_show_their_level_and_no_rating(tmp_path):
    from chumai import render
    from chumai.jackets import JacketStore
    from chumai.playlog import Badge, to_entry

    html = '<div class="main_wrapper">' + MAIMAI_ROW.format(track=1).replace("diff_master", "diff_utage").replace(
        "天体観測", "[協]Love You") + "</div>"
    utage = net_parsers.parse_maimai_playlog(html)[0]
    assert (utage.title, utage.difficulty) == ("[協]Love You", "UTAGE")  # 宴 is no longer skipped

    store = JacketStore(tmp_path)
    store.load_index([{"id": "8330", "title": "ヤババイナ", "we_kanji": "狂", "we_star": "9", "image": "a.jpg"}],
                     [{"title": "[協]Love You", "lev_utage": "12?", "kanji": "協", "image_url": "b.png"}])
    assert store.unrated_level("ヤババイナ", "WORLD'S END") == "狂☆5"  # we_star 9 is ☆5 (1, 3, 5, 7, 9)
    assert store.unrated_level("Love You", "UTAGE") == "12?"  # also without the [協]

    e = to_entry("maimai", utage, SongDB(), store.unrated_level)
    assert (e.level, e.rating_text, e.rated, e.rank) == ("12?", "-", False, "SSS+")
    we = net_parsers.PlayRecord("2026/09/29 12:00", 1, "ヤババイナ", "WORLD'S END", 1_005_123, None, None, True, None)
    w = to_entry("chunithm", we, SongDB(), store.unrated_level)
    assert (w.level, w.rating_text) == ("狂☆5", "-")
    png = render.render_credit("chunithm", "p", [w], [Badge("new")], "2026/09/29")  # draws; no rating in the avg
    assert png


class FakeNet:
    pages: dict = {}

    def __init__(self, game, clal):
        self.clal = clal

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def get(self, path):
        return self.pages[path]

    async def get_bytes(self, url):
        raise botmod.SegaError("no images in tests")


def test_check_playlog_posts_only_new_credits(tmp_path, monkeypatch):
    playlog = (FIX / "playlog.html").read_bytes()
    FakeNet.pages = {
        "/mobile/record/playlog": playlog,
        "/mobile/home/playerData/": (FIX / "player_data.html").read_bytes(),
    }
    monkeypatch.setattr(botmod, "NetClient", FakeNet)
    sent = []

    class Channel:
        async def send(self, file):
            sent.append(file.filename)

    links = LinkStore(tmp_path / "db.sqlite")
    links.set_sega_token(1, "tok")
    records = net_parsers.parse_chunithm_playlog(playlog)
    credits = net_parsers.group_credits(records)
    last_key = credits[-3][-1].key  # the last two credits are "new"
    links.set_playlog(1, "chunithm", 99, last_key)
    fake_bot = SimpleNamespace(
        links=links, songdb=SongDB(), jackets=SimpleNamespace(unrated_level=lambda title, diff: None),
        config=SimpleNamespace(jacket_dir=str(tmp_path / "j"), new_versions={"chunithm": [], "maimai": []}),
        get_channel=lambda cid: Channel(),
    )

    assert asyncio.run(botmod.check_playlog(fake_bot, 1, "chunithm", 99, last_key)) is True
    assert len(sent) == 2
    new_key = links.playlogs()[0][3]
    assert new_key == records[0].key
    # nothing new the second time
    assert asyncio.run(botmod.check_playlog(fake_bot, 1, "chunithm", 99, new_key)) is False
    assert len(sent) == 2


def test_check_playlog_without_updating_key(tmp_path, monkeypatch):
    playlog = (FIX / "playlog.html").read_bytes()
    FakeNet.pages = {
        "/mobile/record/playlog": playlog,
        "/mobile/home/playerData/": (FIX / "player_data.html").read_bytes(),
    }
    monkeypatch.setattr(botmod, "NetClient", FakeNet)
    sent = []

    class Channel:
        async def send(self, file):
            sent.append(file.filename)

    links = LinkStore(tmp_path / "db.sqlite")
    links.set_sega_token(1, "tok")
    links.set_playlog(1, "chunithm", 99, "9999")  # already up to date
    credits = net_parsers.group_credits(net_parsers.parse_chunithm_playlog(playlog))
    fake_bot = SimpleNamespace(
        links=links, songdb=SongDB(), jackets=SimpleNamespace(unrated_level=lambda title, diff: None),
        config=SimpleNamespace(jacket_dir=str(tmp_path / "j"), new_versions={"chunithm": [], "maimai": []}),
        get_channel=lambda cid: Channel(),
    )
    before = credits[-2][-1].key
    assert asyncio.run(botmod.check_playlog(fake_bot, 1, "chunithm", 99, before, update=False))
    assert len(sent) == 1
    assert links.playlogs()[0][3] == "9999"  # subscription untouched


def _play(key_time, track, title, score, new, diff="MASTER"):
    return net_parsers.PlayRecord(key_time, track, title, diff, score, None, None, new, None)


def test_badges_new_tie_best():
    from chumai.playlog import badges

    cache = {("A", "MASTER"): 1_000_000, ("B", "MASTER"): 990_000}
    plays = [
        _play("2026/01/01 09:00", 1, "A", 999_000, True),  # before the cache: improvement unknown
        _play("2026/01/02 10:00", 1, "A", 1_002_500, True),
        _play("2026/01/02 10:00", 2, "A", 1_002_500, False),
        _play("2026/01/02 10:00", 3, "B", 980_000, False),
        _play("2026/01/02 10:00", 4, "C", 970_000, True),  # first play of the chart
        _play("2026/01/02 11:00", 1, "D", 950_000, False),  # not in the cache: use the record pages
    ]
    now = {("D", "MASTER"): 960_000}
    out = badges(plays, cache, "2026/01/01 09:00#01", now)
    got = [(out[p.key].kind, out[p.key].delta, out[p.key].best) if p.key in out else None for p in plays]
    assert got == [
        ("new", None, None),
        ("new", 2500, None),
        ("tie", None, None),
        ("best", None, 990_000),
        ("new", None, None),
        ("best", None, 960_000),
    ]


def test_badges_maimai_tie():
    from chumai.playlog import badges

    p = _play("2026/01/02 10:00", 1, "X", 100.5123, False, "DX Master")
    out = badges([p], {("X", "DX Master"): 100.5123}, "2026/01/01 00:00#01", {})
    assert out[p.key].kind == "tie"


def test_best_score_store(tmp_path):
    store = LinkStore(tmp_path / "db.sqlite")
    assert store.get_bests(1, "chunithm") == ({}, None)
    store.save_bests(1, "chunithm", {("A", "MASTER"): 1_000_000}, "k1")
    store.save_bests(1, "chunithm", {("A", "MASTER"): 1_001_000, ("B", "EXPERT"): 990_000}, "k2")
    assert store.get_bests(1, "chunithm") == ({("A", "MASTER"): 1_001_000, ("B", "EXPERT"): 990_000}, "k2")
    store.set_sega_token(1, "tok")
    store.delete_sega_token(1)  # logging out also forgets the scores
    assert store.get_bests(1, "chunithm") == ({}, None)


def test_missing_permissions():
    import discord

    class Channel:
        def __init__(self, **perms):
            self.guild = SimpleNamespace(me=object())
            self._perms = discord.Permissions(**perms)

        def permissions_for(self, member):
            return self._perms

    assert botmod.missing_permissions(Channel(view_channel=True, send_messages=True, attach_files=True)) == []
    assert botmod.missing_permissions(Channel(view_channel=True, send_messages=True)) == ["파일 첨부"]
    assert "파일 첨부" in botmod.permission_message(["파일 첨부"])
    assert botmod.missing_permissions(SimpleNamespace()) == []  # DMs etc.: nothing to check


def test_badges_show_rating_gain():
    from fractions import Fraction

    from chumai.playlog import b50_sum, badges
    from test_tools import _db

    db = _db()
    cache = {("Aleph-0", "MASTER"): 1_000_000, ("AXION", "MASTER"): 1_007_500}
    before = b50_sum("chunithm", db, [], cache)
    assert before == (Fraction("15.9") + Fraction("16.7")) / 50  # 14.9 + 1.00, 14.7 + 2.00
    plays = [_play("2026/01/02 10:00", 1, "Aleph-0", 1_009_000, True),
             _play("2026/01/02 10:00", 2, "AXION", 1_007_000, False)]
    out = badges(plays, cache, "2026/01/01 00:00#01", {}, db, [], "chunithm")
    assert out[plays[0].key].gain == Fraction("1.15") / 50  # 15.90 -> 17.05
    assert out[plays[1].key].gain is None


def test_rating_change_and_store(tmp_path):
    from chumai import render

    assert render._rating_change("chunithm", "16.05", "16.07") == "+0.02"
    assert render._rating_change("maimai", "12573", "12608") == "+35"
    assert render._rating_change("chunithm", "16.07", "16.07") is None
    assert render._rating_change("chunithm", None, "16.07") is None
    store = LinkStore(tmp_path / "db.sqlite")
    assert store.get_rating(1, "chunithm") is None
    store.save_rating(1, "chunithm", "16.05")
    store.save_rating(1, "chunithm", "16.07")
    assert store.get_rating(1, "chunithm") == "16.07"


def test_first_check_of_an_automatic_play_log(tmp_path, monkeypatch):
    import asyncio

    from chumai import bot as botmod
    from chumai.storage import PLAYLOG_NEW, PLAYLOG_SKIP
    from test_features_commands import _bot

    class FakeNet:
        clal = "t1"

        def __init__(self, game, token):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    fails = {"maimai": True, "chunithm": False}

    async def start(bot, net, discord_id, game):
        if fails[game]:
            raise botmod.SegaError("no maimai data")
        return "2026/09/30 18:00#01"

    monkeypatch.setattr(botmod, "NetClient", FakeNet)
    monkeypatch.setattr(botmod, "start_playlog", start)
    bot = _bot(tmp_path, monkeypatch)
    bot._auto_tries = {}
    bot.links.set_sega_token(1, "t1")
    bot.links.add_auto_playlogs(5, ("chunithm", "maimai"))

    async def run():
        for _ in range(botmod.AUTO_PLAYLOG_TRIES):
            for game in ("chunithm", "maimai"):
                if dict(((d, g), k) for d, g, _, k in bot.links.playlogs()).get((1, game)) == PLAYLOG_NEW:
                    await bot._start_auto_playlog(1, game, 5)

    asyncio.run(run())
    keys = {g: k for d, g, _, k in bot.links.playlogs()}
    assert keys == {"chunithm": "2026/09/30 18:00#01"}  # maimai was left out
    row = bot.links._db.execute("SELECT last_key FROM playlog_subs WHERE game = 'maimai'").fetchone()
    assert row[0] == PLAYLOG_SKIP


def test_own_settings_wait_while_everyone_is_posted(tmp_path, monkeypatch):
    import asyncio

    from test_features_commands import _bot, _interaction

    from chumai.bot import PLAYLOG_ALL_SETTING

    bot = _bot(tmp_path, monkeypatch)
    bot.links.set_sega_token(1, "t1")
    bot.links.set_setting(PLAYLOG_ALL_SETTING, "77")
    for sub in ("on", "off"):
        log = []
        asyncio.run(bot.tree.get_command("playlog").get_command(sub).callback(_interaction(log), game="maimai"))
        assert "<#77>" in log[-1][1] and log[-1][2]["ephemeral"]


def test_best_scores_saved_at_login(tmp_path, monkeypatch):
    import asyncio

    from chumai import bot as botmod
    from test_features_commands import _bot

    class FakeNet:
        clal = "t1"

        def __init__(self, game, token):
            self.game = game

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    started = []

    async def start(bot, net, discord_id, game, progress=None):
        if game == "maimai":
            raise botmod.SegaError("never played")
        started.append(game)
        for _ in range(3 if progress else 0):  # a few of its pages
            await progress("CHUNITHM page")
        bot.links.save_bests(discord_id, game, {("A", "MASTER"): 1_000_000.0}, "k")
        return "2026/09/30 18:00#01"

    monkeypatch.setattr(botmod, "NetClient", FakeNet)
    monkeypatch.setattr(botmod, "start_playlog", start)
    bot = _bot(tmp_path, monkeypatch)
    bot.links.set_sega_token(1, "t1")
    shown = []

    class Message:
        async def edit(self, content):
            shown.append(content)

    progress = botmod.LoginProgress("로그인 완료")
    progress.message = Message()
    asyncio.run(botmod.save_all_bests(bot, 1, progress))
    assert started == ["chunithm"] and bot.links.playlogs() == []  # nothing else turned on
    assert "▰" in shown[0] and progress.done == progress.total  # a failed game counts as done
    assert shown[-1].endswith("CHUNITHM 1개 보면 · maimai 기록 없음") and "✅ 저장 완료" in shown[-1]

    bot.links.set_setting(botmod.PLAYLOG_ALL_SETTING, "5")  # with /playlog all, its first check too
    asyncio.run(botmod.save_all_bests(bot, 1))
    keys = {g: k for _, g, _, k in bot.links.playlogs()}
    assert keys == {"chunithm": "2026/09/30 18:00#01"}  # maimai: the next check tries it, as for anyone



def test_chunithm_playlog_ultima():
    html = (FIX / "playlog.html").read_text(encoding="utf-8").replace("musiclevel_master", "musiclevel_ultimate", 1)
    records = net_parsers.parse_chunithm_playlog(html)
    assert "ULTIMA" in {r.difficulty for r in records} and "ULTIMATE" not in {r.difficulty for r in records}
