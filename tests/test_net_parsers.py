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


def test_chunithm_profile_parts():
    player = net_parsers.parse_chunithm_player(_read("chunithm_net/player_data.html"))
    assert player.icon_url.endswith("2c20c7ac326c1a9d.png")
    assert (player.title, player.title_rarity) == ("ネコぱら", "silver")
    plate = net_parsers.parse_chunithm_nameplate(_read("chunithm_net/collection_customise.html"))
    assert plate and plate.endswith(".png")


def test_maimai_profile_parts():
    html = (
        '<img src="https://maimaidx-eng.com/maimai-mobile/img/Icon/abc.png" class="w_112 f_l">'
        '<div class="name_block">X</div><div class="rating_block">1</div>'
        '<div class="trophy_block trophy_Gold p_3"><div class="trophy_inner_block"><span>称号</span></div></div>'
        '<img src="https://maimaidx-eng.com/maimai-mobile/img/NamePlate/p.png">'
    )
    p = net_parsers.parse_maimai_player(html)
    assert p.icon_url.endswith("/Icon/abc.png") and p.plate_url.endswith("/NamePlate/p.png")
    assert (p.title, p.title_rarity) == ("称号", "gold")
