import io
import random
from fractions import Fraction

from PIL import Image

from chumai import features, tools
from chumai.b50 import make_entry, select_b50
from chumai.songdb import SongDB, search

SEEDS = {
    "songs-chunithm": [
        {"id": "A", "title": "Aleph-0", "altTitles": [], "searchTerms": ["aleph zero"], "artist": "LeaF",
         "data": {"genre": "ORIGINAL"}},
        {"id": "B", "title": "AXION", "altTitles": [], "searchTerms": [], "artist": "x", "data": {"genre": "x"}},
        {"id": "C", "title": "Easy Song", "altTitles": [], "searchTerms": [], "artist": "x", "data": {"genre": "x"}},
    ],
    "charts-chunithm": [
        {"songID": "A", "difficulty": "MASTER", "level": "14+", "levelNum": 14.9,
         "data": {"inGameID": 428, "displayVersion": "CHUNITHM PARADISE"}},
        {"songID": "A", "difficulty": "WORLD'S END", "level": "☆5", "levelNum": 0,
         "data": {"inGameID": 8000, "displayVersion": "CHUNITHM PARADISE"}},
        {"songID": "B", "difficulty": "MASTER", "level": "14+", "levelNum": 14.7,
         "data": {"inGameID": 2000, "displayVersion": "CHUNITHM X-VERSE-X"}},
        {"songID": "C", "difficulty": "EXPERT", "level": "12", "levelNum": 12.0,
         "data": {"inGameID": 3000, "displayVersion": "CHUNITHM SUN"}},
    ],
    "songs-maimaidx": [], "charts-maimaidx": [],
}


def _db():
    db = SongDB()
    db.load(SEEDS)
    return db


def test_search_and_catalog():
    db = _db()
    assert search(db, "chunithm", "aleph")[0].title == "Aleph-0"
    assert search(db, "chunithm", "aleph zero")[0].title == "Aleph-0"
    assert search(db, "chunithm", "AXON")[0].title == "AXION"  # fuzzy
    assert search(db, "chunithm", "Aleph-0")[0].music_id == 428


def test_reach():
    assert tools.reach_score("chunithm", 14.7, 16.7) == 1_007_500
    assert tools.reach_score("chunithm", 14.7, 16.9) is None
    assert tools.reach_score("maimai", 14.7, 330) == 100.5
    assert tools.chart_rating("maimai", 14.7, tools.reach_score("maimai", 14.7, 300)) >= 300
    assert tools.chart_rating("maimai", 14.7, tools.reach_score("maimai", 14.7, 300) - 0.0001) < 300


def test_charts_in_range_skips_worlds_end():
    db = _db()
    got = tools.charts_in_range(db, "chunithm", 0, 20)
    assert [c.difficulty for _, c in got] == ["MASTER", "MASTER", "EXPERT"]
    assert len(tools.random_charts(db, "chunithm", 14.7, 14.9, 4, random.Random(1))) == 2


def test_find_chart_loose():
    song = search(_db(), "chunithm", "Aleph-0")[0]
    assert tools.find_chart(song, "mas").difficulty == "MASTER"
    assert tools.find_chart(song, "EXP") is None


def test_what_if_and_recommend():
    db = _db()
    entries = [make_entry("chunithm", f"S{i}", "MASTER", "14", 14.0, 1_000_000, None, False) for i in range(30)]
    entries += [make_entry("chunithm", f"N{i}", "MASTER", "14", 13.5, 1_000_000, None, True) for i in range(20)]
    b = select_b50("chunithm", "p", entries)
    aleph = search(db, "chunithm", "Aleph-0")[0]
    w = tools.what_if(b, aleph, tools.find_chart(aleph, "MAS"), 1_009_000, False)
    assert w.counted and w.after > w.before
    low = tools.what_if(b, aleph, tools.find_chart(aleph, "MAS"), 500_000, False)
    assert not low.counted and low.after == low.before

    assert tools.recommend(db, b, ["CHUNITHM X-VERSE-X"], 5, random.Random(0)) == []  # 15.x charts: too hard

    # a stronger player (about 15.9): the 14.x charts become fair targets
    strong = [make_entry("chunithm", f"S{i}", "MASTER", "14", 14.0, 1_009_000, None, False) for i in range(30)]
    strong += [make_entry("chunithm", f"N{i}", "MASTER", "13+", 13.5, 1_007_500, None, True) for i in range(20)]
    sb = select_b50("chunithm", "p", strong)
    recs = tools.recommend(db, sb, ["CHUNITHM X-VERSE-X"], 5, random.Random(0))
    assert recs and all(r.gain > 0 and r.after >= r.before for r in recs)
    for r in recs:
        assert r.target_score == tools.chunithm_target(float(sb.total), r.chart.level_const)


def test_guess_helpers(tmp_path):
    song = search(_db(), "chunithm", "Aleph-0")[0]
    assert features._answer_matches(song, "aleph-0")
    assert features._answer_matches(song, "Aleph 0")
    assert features._answer_matches(song, "aleph zero")
    assert not features._answer_matches(song, "AXION")
    p = tmp_path / "j.png"
    Image.new("RGB", (300, 300), (255, 0, 0)).save(p)
    hint = Image.open(io.BytesIO(features._crop_hint(str(p), random.Random(0))))
    assert hint.size == (300, 300)


def test_parse_level():
    import pytest

    assert tools.parse_level("14", "chunithm") == (14.0, 14.4)
    assert tools.parse_level("14+", "chunithm") == (14.5, 14.9)
    assert tools.parse_level("14", "maimai") == (14.0, 14.5)
    assert tools.parse_level("14+", "maimai") == (14.6, 14.9)
    assert tools.parse_level("13.5", "chunithm") == (13.5, 13.5)
    assert tools.parse_level("14.0-14.8", "chunithm") == (14.0, 14.8)
    assert tools.parse_level("13+-14", "chunithm") == (13.5, 14.4)
    assert tools.parse_level("15-", "chunithm") == (15.0, 16.0)
    assert tools.parse_level("-12", "chunithm") == (1.0, 12.4)
    with pytest.raises(ValueError):
        tools.parse_level("abc", "chunithm")
    with pytest.raises(ValueError):
        tools.parse_level("15-14", "chunithm")


def test_chunithm_target_follows_the_roadmap():
    t = tools.chunithm_target
    assert t(16.07, 15.6) is None  # half a level below your rating: too hard to plan for
    assert t(12.6, 12.0) == 1_000_000  # low ratings: SS 0.6 below
    assert t(12.6, 11.0) >= 1_007_000  # ~SSS 1.6 below
    assert 1_005_000 <= t(16.5, 15.2) < 1_007_500  # high ratings: SS+ 1.3 below
    assert t(17.3, 15.5) == 1_007_500  # SSS 1.8 below
    assert t(15.0, 10.0) == 1_009_000
    scores = [t(16.07, c / 10) for c in range(135, 152)]
    assert all(a >= b for a, b in zip(scores, scores[1:]) if b is not None)  # easier chart, higher target
    assert tools.chunithm_advice(16.07).startswith("14 비중")
    assert tools.chunithm_advice(17.53) == "15를 SSS+로 · 점수작"
    assert tools.chunithm_advice(9.0).startswith("적정 레벨")


def test_recommend_maimai_stays_near_usual_difficulty():
    from chumai.songdb import CatalogChart, CatalogSong

    db = _db()
    db.catalog["maimai"] = [CatalogSong("maimai", f"M{c}", "", "maimai", [f"m{c}"],
                                        [CatalogChart("Master", "13", c / 10, "maimai")]) for c in (123, 128, 132)]
    entries = [make_entry("maimai", f"S{i}", "Master", "12", 12.0 + (i % 5) / 10, 100.0, None, False)
               for i in range(35)]
    entries += [make_entry("maimai", f"N{i}", "Master", "12", 11.5, 100.0, None, True) for i in range(15)]
    b = select_b50("maimai", "p", entries)
    recs = tools.recommend(db, b, ["maimai でらっくす PRiSM PLUS"], 5, random.Random(0))
    assert {r.song.title for r in recs} == {"M123"}  # 12.8 / 13.2 are above the usual difficulty


def test_font_download(tmp_path):
    import asyncio

    from aiohttp import web

    from chumai import fonts

    async def main():
        app = web.Application()
        app.router.add_get("/font.otf", lambda r: web.Response(body=b"OTTO" + b"x" * 1000))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            first = await fonts.ensure_font(tmp_path, f"http://127.0.0.1:{port}/font.otf")
            again = await fonts.ensure_font(tmp_path, "http://127.0.0.1:1/unreachable")  # cached: no download
            missing = await fonts.ensure_font(tmp_path / "other", "http://127.0.0.1:1/unreachable")
        finally:
            await runner.cleanup()
        return first, again, missing

    first, again, missing = asyncio.run(main())
    assert first == again and first.read_bytes().startswith(b"OTTO")
    assert missing is None and not list((tmp_path / "other").iterdir())


def test_maimai_targets_are_rank_borders():
    es = [make_entry("maimai", f"A{i}", "Master", "12", 12.0 + i / 10, 100.0, None, False) for i in range(5)]  # SSS ~12.4
    es += [make_entry("maimai", f"B{i}", "Master", "13", 12.5 + i / 10, 99.6, None, False) for i in range(4)]  # SS+ ~12.8
    es += [make_entry("maimai", c, "Master", "13", k, 97.5, None, False) for c, k in (("C", 13.4), ("D", 13.5))]
    reach = tools.maimai_reach(es)
    assert reach[100.0] == 12.4 and reach[99.5] == 12.8 and reach[97.0] == 13.4  # the single 13.5 is a fluke
    assert 100.5 not in reach
    assert tools.maimai_target(reach, 12.5) == 100.0  # a little above what you've done
    assert tools.maimai_target(reach, 12.9) == 99.5
    assert tools.maimai_target(reach, 13.2) == 97.0
    assert tools.maimai_target(reach, 13.7) is None
    assert tools.maimai_reach_text(reach) == "SSS ~12.4 · SS+ ~12.8 · SS ~12.8"
