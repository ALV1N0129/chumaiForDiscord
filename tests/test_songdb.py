from chumai.b50 import b50_from_chunithm_net, b50_from_maimai_net
from chumai.net_parsers import ChunithmRecord, MaimaiRecord, PlayerInfo
from chumai.songdb import SongDB, level_to_min_const

SEEDS = {
    "songs-chunithm": [{"id": "S1", "title": "Aleph-0", "data": {"genre": "ORIGINAL"}}],
    "charts-chunithm": [
        {"songID": "S1", "difficulty": "EXPERT", "level": "13", "levelNum": 13.4,
         "data": {"inGameID": 428, "displayVersion": "CHUNITHM PARADISE"}},
    ],
    "songs-maimaidx": [
        {"id": "M1", "title": "天体観測", "altTitles": [], "data": {"genre": "POPS＆アニメ"}},
        {"id": "M2", "title": "Link", "altTitles": [], "data": {"genre": "niconico＆ボーカロイド"}},
        {"id": "M3", "title": "Link", "altTitles": [], "data": {"genre": "maimai"}},
    ],
    "charts-maimaidx": [
        {"songID": "M1", "difficulty": "DX Master", "level": "14", "levelNum": 14.2,
         "data": {"displayVersion": "maimaiでらっくす CiRCLE"}},
        {"songID": "M2", "difficulty": "Master", "level": "13", "levelNum": 13.0,
         "data": {"displayVersion": "maimai ORANGE"}},
        {"songID": "M3", "difficulty": "Master", "level": "13+", "levelNum": 13.7,
         "data": {"displayVersion": "maimai GreeN"}},
    ],
}


def _db() -> SongDB:
    db = SongDB()
    db.load(SEEDS)
    return db


def test_lookup():
    db = _db()
    assert db.chunithm_chart(428, "EXPERT").level_const == 13.4
    assert db.maimai_chart("天体観測", "DX Master").level_const == 14.2
    # duplicate title resolved by the (international, English) genre name
    assert db.maimai_chart("Link", "Master", "maimai").level_const == 13.7
    assert db.maimai_chart("Link", "Master", "niconico&VOCALOID").level_const == 13.0
    assert db.maimai_chart("天体観測", "Master") is None


def test_level_fallback():
    assert level_to_min_const("13+", "maimai") == 13.6
    assert level_to_min_const("13+", "chunithm") == 13.5
    assert level_to_min_const("14", "maimai") == 14.0


def test_chunithm_net_b50():
    b = b50_from_chunithm_net(
        PlayerInfo("p", "15.10"),
        [ChunithmRecord(428, "Aleph-0", "EXPERT", 1_005_037), ChunithmRecord(9999, "?", "MASTER", 1_000_000)],
        [],
        _db(),
    )
    assert b.official_rating == "15.10" and b.source == "CHUNITHM-NET"
    assert str(b.old[0].rating_text) == "14.90"  # 13.4 + 1.50
    assert b.old[1].level_const == 0.0  # unknown chart


def test_maimai_net_b50_new_old_split():
    records = [
        MaimaiRecord("天体観測", "POPS&ANIME", "DX Master", "14", 100.5, "AP"),
        MaimaiRecord("Link", "maimai", "Master", "13+", 100.0, None),
        MaimaiRecord("Brand New", "maimai", "DX Master", "14+", 100.5, None),
    ]
    b = b50_from_maimai_net(PlayerInfo("p", "1000"), records, _db(), ["maimaiでらっくす CiRCLE"])
    assert [e.title for e in b.old] == ["Link"]
    assert sorted(e.title for e in b.new) == ["Brand New", "天体観測"]
    assert b.old[0].rating_text == str(int(13.7 * 21.6))
