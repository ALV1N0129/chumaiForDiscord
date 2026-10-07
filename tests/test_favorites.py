from chumai import favorites, net_parsers

PAGE = """<form action="x/set" method="post"><select name="idx"><option value="99">All</option></select>
<div id="list"><div class="screw_block m_10 f_15 favorite_p_s" name=genre2>niconico</div>
<div class="m_t_10" name=genre2>
<label><div class="favorite_checkbox"><input type="checkbox" id="favorite" name="music[]" value="AAA" class="f_l"/>
<div class="favorite_music_name break">Link</div></div></label>
<label><div class="favorite_checkbox"><input type="checkbox" id="favorite" name="music[]" value="BBB" checked class="f_l"/>
<div class="favorite_music_name break">シャルル</div></div></label>
</div><div class="screw_block m_10 f_15 favorite_p_s" name=genre5>maimai</div>
<div class="m_t_10" name=genre5>
<label><div class="favorite_checkbox"><input type="checkbox" id="favorite" name="music[]" value="CCC" class="f_l"/>
<div class="favorite_music_name break">Link</div></div></label>
<label><div class="favorite_checkbox"><input type="checkbox" id="favorite" name="music[]" value="DDD" class="f_l"/>
<div class="favorite_music_name break">Xaleid&#9670;scopiX</div></div></label>
</div><input type="hidden" name="token" value="t" /></div></form>"""


def test_parse_favorites():
    rows = net_parsers.parse_maimai_favorites(PAGE)
    assert [(r.genre, r.title, r.value, r.checked) for r in rows] == [
        (2, "Link", "AAA", False), (2, "シャルル", "BBB", True), (5, "Link", "CCC", False),
        (5, "Xaleid◆scopiX", "DDD", False)]


def test_pick_keeps_the_genre_of_same_titles():
    rows = net_parsers.parse_maimai_favorites(PAGE)
    found, missing = favorites.pick(rows, [["Link", 5], ["シャルル", 2], ["Gone", 1]])
    assert [r.value for r in found] == ["CCC", "BBB"] and missing == ["Gone"]
