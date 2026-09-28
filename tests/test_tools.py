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
    assert {r.song.title for r in recs} == {"M123", "M128"}  # 13.2 is too far above what you play
    assert {r.song.title: r.target_score for r in recs} == {"M123": 100.0, "M128": 99.0}


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


def test_maimai_skill_expects_a_typical_play():
    # about 100.0 at 12.0, losing 0.3% per +0.1 constant, plus one lucky 13.5
    pts = [(12.0 + i / 10, 100.0 - 3 * i / 10) for i in range(8) for _ in range(3)] + [(13.5, 99.5)]
    skill = tools.MaimaiSkill(pts)
    assert abs(skill.expected(12.3) - 99.1) < 0.1
    assert skill.expected(13.5) is None  # one lucky score is not enough to say
    lucky = tools.MaimaiSkill(pts + [(12.9, 99.9)])
    assert lucky.expected(12.9) <= lucky.expected(12.8) <= lucky.expected(12.7)  # and never lifts the curve
    assert skill.expected(9.0) is None  # nothing played near it
    reach = skill.reach()
    assert reach[100.0] == 11.9 and reach[99.5] == 12.1 and reach[99.0] == 12.3
    assert tools.maimai_reach_text(reach) == "SSS+ ~11.7 · SSS ~11.9 · SS+ ~12.1 · SS ~12.3"


def test_maimai_targets_are_rank_borders():
    assert tools.maimai_target(99.2) == 99.5  # a small stretch
    assert tools.maimai_target(99.1) == 99.0  # 99.5 is too far: the border you should get
    assert tools.maimai_target(98.2) == 98.0
    assert tools.maimai_target(100.3) == 100.5
    assert tools.maimai_target(96.5) is None  # below S: too hard
    assert tools.maimai_target(None) is None
    assert tools.maimai_target(99.2, best=99.3) == 99.5  # played: must beat your best
    assert tools.maimai_target(99.2, best=99.5) is None


def test_recommend_maimai_uses_every_played_chart():
    from chumai.songdb import CatalogChart, CatalogSong

    db = _db()
    db.catalog["maimai"] = [
        CatalogSong("maimai", "Played", "", "maimai", ["played"],
                    [CatalogChart("Master", "12", 12.3, "maimai"), CatalogChart("DX Master", "12", 12.3, "maimai")]),
        CatalogSong("maimai", "Done", "", "maimai", ["done"], [CatalogChart("Master", "12", 12.3, "maimai")]),
    ]
    entries = [make_entry("maimai", f"S{i}", "Master", "12", 12.0 + (i % 5) / 10, 100.0 - (i % 5) * 0.3,
                          None, False) for i in range(35)]
    entries += [make_entry("maimai", f"N{i}", "Master", "12", 11.5, 100.0, None, True) for i in range(15)]
    b = select_b50("maimai", "p", entries)
    b.played = {("Played", "Master"): 98.9, ("Done", "Master"): 99.6}
    recs = tools.recommend(db, b, ["maimai でらっくす PRiSM PLUS"], 5, random.Random(0))
    assert len(recs) == 1  # one chart per song; "Done" already beats the target
    r = recs[0]
    assert r.song.title == "Played" and r.target_score == 99.5
    if r.chart.difficulty == "Master":
        assert r.best == 98.9
    assert r.expected is not None and abs(r.expected - 99.1) < 0.2


def test_recommend_maimai_prefers_charts_that_play_easy():
    from chumai.songdb import CatalogChart, CatalogSong

    db = _db()
    db.catalog["maimai"] = [CatalogSong("maimai", t, "", "maimai", [t.lower()],
                                        [CatalogChart("Master", "12+", 12.8, "maimai")])
                            for t in ("Sweet", "Plain", "Sour")]
    entries = [make_entry("maimai", f"S{i}", "Master", "12", 12.0 + (i % 5) / 10, 100.0 - (i % 5) * 0.25,
                          None, False) for i in range(35)]
    entries += [make_entry("maimai", f"N{i}", "Master", "12", 11.5, 100.0, None, True) for i in range(15)]
    b = select_b50("maimai", "p", entries)
    honey = {"sweet": 0.5, "sour": -0.4}
    recs = tools.recommend(db, b, ["maimai でらっくす PRiSM PLUS"], 3, random.Random(0),
                           honey=lambda title, diff: honey.get(title.lower()))
    by_title = {r.song.title: r for r in recs}
    assert recs[0].song.title == "Sweet" and recs[0].honey == 0.5
    assert by_title["Sweet"].target_score > by_title["Plain"].target_score  # plays like 12.3
    assert "Sour" not in by_title or by_title["Sour"].target_score < by_title["Plain"].target_score


def test_slim_seeds_load_the_same(tmp_path):
    import asyncio

    from chumai.songdb import SEED_NAMES, SLIM_NAME, SongDB, slim_seed

    full, slim = SongDB(), SongDB()
    full.load(SEEDS)
    slim.load({n: slim_seed(n, SEEDS[n]) for n in SEED_NAMES})
    assert full.chunithm == slim.chunithm and full.maimai == slim.maimai
    assert full.catalog == slim.catalog

    # an older version cached the full seeds: they are slimmed without downloading
    import json
    for n in SEED_NAMES:
        (tmp_path / f"{n}.json").write_text(json.dumps(SEEDS[n]), encoding="utf-8")
    db = SongDB()
    asyncio.run(db.load_or_update(tmp_path, base_url="http://127.0.0.1:1/unreachable"))
    assert (tmp_path / SLIM_NAME).exists() and db.catalog == full.catalog


def test_songdb_download_streams_to_disk(tmp_path):
    import asyncio
    import json

    from aiohttp import web

    from chumai import jsonstream
    from chumai.songdb import SEED_NAMES, SongDB

    async def main():
        app = web.Application()
        for n in SEED_NAMES:
            app.router.add_get(f"/seeds/{n}.json", lambda r, n=n: web.json_response(SEEDS[n]))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            db = SongDB()
            await db.load_or_update(tmp_path, base_url=f"http://127.0.0.1:{port}/seeds")
        finally:
            await runner.cleanup()
        return db

    db = asyncio.run(main())
    full = SongDB()
    full.load(SEEDS)
    assert db.catalog == full.catalog
    assert not list(tmp_path.glob("*.download*"))  # temporary files cleaned up

    p = tmp_path / "items.json"
    p.write_text(json.dumps([{"a": 1.5}, {"b": [1, 2]}]))
    assert list(jsonstream.iter_items(p)) == [{"a": 1.5}, {"b": [1, 2]}]
