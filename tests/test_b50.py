from fractions import Fraction

from chumai.b50 import build_b50
from chumai.render import render_b50
from chumai.tachi import parse_bundle

NEW = "CHUNITHM X-VERSE-X"


def _chunithm_body(n_old: int, n_new: int):
    songs, charts, pbs = [], [], []
    for i in range(n_old + n_new):
        is_new = i >= n_old
        songs.append({"id": f"S{i}", "title": f"Song {i}", "artist": "a", "data": {"genre": "x"}})
        charts.append(
            {
                "chartID": f"C{i}",
                "songID": f"S{i}",
                "difficulty": "MASTER",
                "level": "14",
                "levelNum": 14.0 + (i % 10) / 10,
                "data": {"displayVersion": NEW if is_new else "CHUNITHM SUN", "inGameID": i},
            }
        )
        pbs.append({"chartID": f"C{i}", "scoreData": {"score": 1_005_000, "lamp": "FULL COMBO"}})
    return {"songs": songs, "charts": charts, "pbs": pbs}


def test_chunithm_b50_split_and_total():
    bundle = parse_bundle("tester", _chunithm_body(40, 25))
    b = build_b50("chunithm", bundle, [NEW])
    assert len(b.old) == 30 and len(b.new) == 20
    assert all(not e.is_new for e in b.old) and all(e.is_new for e in b.new)
    # sorted by rating desc
    assert [e.rating for e in b.old] == sorted((e.rating for e in b.old), reverse=True)
    assert b.total == Fraction(int((b.old_sum + b.new_sum) / 50 * 100), 100)
    assert b.old[0].lamp == "FC"


def test_old_api_shape_with_song_version_and_nested_song():
    body = {
        "songs": [{"id": 1, "title": "Old", "data": {"displayVersion": "maimaiでらっくす CiRCLE"}}],
        "charts": [
            {"chartID": "a", "songID": 1, "difficulty": "DX Master", "level": "14+", "levelNum": 14.7, "data": {}},
            {
                "chartID": "b",
                "song": {"id": "S2", "title": "Nested"},
                "difficulty": "Re:Master",
                "level": "14",
                "levelNum": 14.2,
                "data": {"displayVersion": "maimai FiNALE"},
            },
        ],
        "pbs": [
            {"chartID": "a", "scoreData": {"percent": 100.5, "lamp": "ALL PERFECT"}},
            {"chartID": "b", "scoreData": {"percent": 99.5, "lamp": "CLEAR"}},
        ],
    }
    b = build_b50("maimai", parse_bundle("u", body), ["maimaiでらっくす CiRCLE"])
    assert [e.title for e in b.new] == ["Old"]
    assert [e.title for e in b.old] == ["Nested"]
    assert b.total == 330 + 298
    assert b.new[0].lamp == "AP" and b.old[0].lamp is None


def test_render_smoke():
    b = build_b50("chunithm", parse_bundle("tester", _chunithm_body(40, 25)), [NEW])
    png = render_b50(b)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
