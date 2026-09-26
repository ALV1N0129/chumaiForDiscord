from pathlib import Path

from chumai import net_parsers

FIX = Path(__file__).parent / "fixtures"


def _read(name: str) -> bytes:
    return (FIX / name).read_bytes()


def test_chunithm_player_data():
    player = net_parsers.parse_chunithm_player(_read("chunithm_net/player_data.html"))
    assert player.name == "ＢｏＡｎｈＤＬＢ"  # noqa: RUF001
    assert player.rating == "15.10"


def test_chunithm_best30():
    records = net_parsers.parse_chunithm_rating_list(_read("chunithm_net/best30.html"))
    assert len(records) == 30
    first = records[0]
    assert (first.idx, first.title, first.difficulty, first.score) == (428, "Aleph-0", "EXPERT", 1_005_037)


def test_chunithm_recent_page():
    records = net_parsers.parse_chunithm_rating_list(_read("chunithm_net/recent10.html"))
    assert len(records) == 10
    assert records[0].title == "To：Be Continued"  # noqa: RUF001


def test_chunithm_error_page():
    assert "200004" in net_parsers.parse_error_message(_read("chunithm_net/200004.html"))


def test_maimai_scores():
    records = net_parsers.parse_maimai_scores(_read("maimai_music_genre.html"), 3)
    assert len(records) == 2  # unplayed chart is skipped
    a, b = records
    assert (a.title, a.difficulty, a.level, a.achievement, a.lamp, a.genre) == (
        "天体観測", "DX Master", "14", 100.6, "AP+", "POPS&ANIME",
    )
    assert (b.title, b.difficulty, b.lamp, b.genre) == ("Link", "Master", "FC", "maimai")


def test_maimai_player():
    html = '<div class="name_block f_l f_16">ＡＬＶ１Ｎ</div><div class="rating_block">14561</div>'
    player = net_parsers.parse_maimai_player(html)
    assert player.rating == "14561" and player.name == "ＡＬＶ１Ｎ"
