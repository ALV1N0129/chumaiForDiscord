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

    recs = tools.recommend(db, b, ["CHUNITHM X-VERSE-X"], 5, random.Random(0))
    titles = {r.song.title for r in recs}
    assert titles == {"Aleph-0", "AXION"}  # Easy Song (12.0) would not beat the floor
    assert all(r.gain > 0 for r in recs)


def test_guess_helpers(tmp_path):
    song = search(_db(), "chunithm", "Aleph-0")[0]
    assert features._answer_matches(song, "aleph-0")
    assert features._answer_matches(song, "Aleph 0")
    assert features._answer_matches(song, "aleph zero")
    assert not features._answer_matches(song, "AXION")
    p = tmp_path / "j.png"
    Image.new("RGB", (300, 300), (255, 0, 0)).save(p)
    assert features._crop_hint(str(p), random.Random(0))[:8] == b"\x89PNG\r\n\x1a\n"


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
