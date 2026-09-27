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
        links=links, songdb=SongDB(), config=SimpleNamespace(jacket_dir=str(tmp_path / "j")),
        get_channel=lambda cid: Channel(),
    )

    assert asyncio.run(botmod.check_playlog(fake_bot, 1, "chunithm", 99, last_key)) is True
    assert len(sent) == 2
    new_key = links.playlogs()[0][3]
    assert new_key == records[0].key
    # nothing new the second time
    assert asyncio.run(botmod.check_playlog(fake_bot, 1, "chunithm", 99, new_key)) is False
    assert len(sent) == 2
