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

    # SS on 13.5~14.0: the seed's 14.x+ charts are harder than anything played
    assert tools.recommend(db, b, ["CHUNITHM X-VERSE-X"], 5, random.Random(0)) == []

    # SSS+ on 14.0 (and SSS on 13.5): the 14.x charts become fair targets
    strong = [make_entry("chunithm", f"S{i}", "MASTER", "14", 14.0 + (i % 10) / 10, 1_009_000, None, False)
              for i in range(30)]
    strong += [make_entry("chunithm", f"N{i}", "MASTER", "13+", 13.5, 1_007_500, None, True) for i in range(20)]
    sb = select_b50("chunithm", "p", strong)
    recs = tools.recommend(db, sb, ["CHUNITHM X-VERSE-X"], 5, random.Random(0))
    assert recs and all(r.gain > 0 and r.after >= r.before for r in recs)
    assert all(r.target_score == 1_009_000 for r in recs)
    assert [r.chart.level_const for r in recs] == sorted(r.chart.level_const for r in recs)  # easiest first


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
    # nothing of 12.8 or harder has been played: no rank is proven there
    assert {r.song.title: r.target_score for r in recs} == {"M123": 100.0}


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


def test_maimai_proven_is_the_usual_rank_nearby():
    # RURU's 14.7~15.0: two SSS, six SS+ -> SS+
    pts = [(14.8, 100.09), (14.9, 99.55), (14.8, 99.97), (14.8, 99.78), (14.8, 99.70), (14.7, 99.86),
           (14.7, 99.69), (14.7, 100.36)]
    assert tools.usual_rank("maimai", pts, 14.7) == 99.5
    more = pts + [(14.6, 100.40), (14.6, 100.25), (14.6, 100.11), (14.6, 100.08), (14.6, 100.0), (14.6, 100.26)]
    assert tools.usual_rank("maimai", more, 14.6) == 100.0  # 8 of 14 are SSS
    assert tools.usual_rank("maimai", pts, 15.0) is None  # nothing that hard
    assert tools.usual_rank("maimai", [(12.0, 100.6), (12.1, 100.0)], 12.0) is None  # too few
    # all played charts: old one-off scores drag the middle down, so the upper quarter counts
    played = [(12.2, 100.2), (12.3, 99.6), (12.1, 99.1), (12.4, 97.5), (12.0, 96.0), (12.2, 94.0), (12.5, 92.0)]
    assert tools.usual_rank("maimai", played, 12.0) == 97.0
    assert tools.usual_rank("maimai", played, 12.0, tools.USUAL_PLAYED) == 99.0  # 5th of 7: 99.1


def test_maimai_entry_and_target():
    from fractions import Fraction

    # 14.3: SSS+ 321, SSS 308, SS+ 300 -> beating 309 needs SSS+
    assert tools.entry_rank("maimai", 14.3, Fraction(309)) == 100.5
    assert tools.entry_rank("maimai", 14.3, Fraction(299)) == 99.5
    assert tools.entry_rank("maimai", 12.0, Fraction(309)) is None
    assert tools.pick_target(100.5, 99.5) == 100.5
    assert tools.pick_target(99.0, 99.5) is None  # your proven rank doesn't count there
    assert tools.pick_target(100.0, 99.0, best=99.8) == 100.0
    assert tools.pick_target(100.0, 99.0, best=100.2) is None  # already there


def test_recommend_maimai_uses_every_played_chart():
    from chumai.songdb import CatalogChart, CatalogSong

    db = _db()
    db.catalog["maimai"] = [
        CatalogSong("maimai", "Played", "", "maimai", ["played"],
                    [CatalogChart("Master", "12", 12.3, "maimai"), CatalogChart("DX Master", "12", 12.3, "maimai")]),
        CatalogSong("maimai", "Done", "", "maimai", ["done"], [CatalogChart("Master", "12", 12.3, "maimai")]),
    ]
    entries = [make_entry("maimai", f"S{i}", "Master", "12", 12.0 + (i % 5) / 10, 99.6, None, False)
               for i in range(35)]
    entries += [make_entry("maimai", f"N{i}", "Master", "12", 11.5, 100.0, None, True) for i in range(15)]
    b = select_b50("maimai", "p", entries)
    b.played = {("Played", "Master"): 99.2, ("Done", "Master"): 99.7}
    recs = tools.recommend(db, b, ["maimai でらっくす PRiSM PLUS"], 5, random.Random(0))
    assert len(recs) == 1  # one chart per song; "Done" already has the SS+
    r = recs[0]
    assert r.song.title == "Played" and r.target_score == 99.5 and r.entry == 99.0  # SS 253 > 252
    if r.chart.difficulty == "Master":
        assert r.best == 99.2


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


def test_jacket_failure_is_retried_later(tmp_path, monkeypatch):
    import asyncio

    from chumai import jackets

    store = jackets.JacketStore(tmp_path)
    store.maimai = {"song": [("maimai", "a.png")]}
    calls = []

    async def download(session, urls):
        calls.append(urls[0])
        return None if len(calls) == 1 else b"PNG"

    monkeypatch.setattr(store, "_download", download)
    key = ("Song", "maimai")
    assert asyncio.run(store.fetch("maimai", [key])) == {}
    assert asyncio.run(store.fetch("maimai", [key])) == {} and len(calls) == 1  # not hammered right away
    store._failed["a.png"] -= jackets.RETRY_FAILED_SECONDS + 1  # ten minutes later
    assert asyncio.run(store.fetch("maimai", [key])) == {0: tmp_path / "maimai" / "a.png"}
    assert "a.png" not in store._failed


def test_jacket_download_retries_a_busy_server():
    import asyncio

    from aiohttp import web

    from chumai import jackets

    hits = []

    async def image(request):
        hits.append(1)
        return web.Response(status=503) if len(hits) == 1 else web.Response(body=b"PNG")

    async def main():
        app = web.Application()
        app.router.add_get("/a.png", image)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            store = jackets.JacketStore(".")
            async with store._session() as s:
                return await store._download(s, [f"http://127.0.0.1:{port}/a.png"])
        finally:
            await runner.cleanup()

    assert asyncio.run(main()) == b"PNG" and len(hits) == 2
