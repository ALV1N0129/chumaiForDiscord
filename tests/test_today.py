from chumai import render
from chumai.bot import play_day
from chumai.net_parsers import PlayRecord
from chumai.storage import LinkStore


def _play(date: str) -> PlayRecord:
    return PlayRecord(date, 1, "Aleph-0", "MASTER", 1007000, None, None, False, None)


def test_a_day_of_play_runs_until_4am():
    assert play_day(_play("2026/09/30 23:50")) == play_day(_play("2026/10/01 03:59"))
    assert play_day(_play("2026/10/01 04:00")) != play_day(_play("2026/10/01 03:59"))


def test_rating_history(tmp_path):
    store = LinkStore(tmp_path / "t.db")
    store.log_rating(1, "chunithm", "16.90", at=100)
    store.log_rating(1, "chunithm", "16.90", at=150)  # unchanged: not stored again
    store.log_rating(1, "chunithm", "16.95", at=200)
    assert store.rating_at(1, "chunithm", 180) == "16.90"
    assert store.rating_at(1, "chunithm", 250) == "16.95"
    assert store.rating_at(1, "chunithm", 50) is None
    store.delete_sega_token(1)  # logging out forgets the history
    assert store.rating_at(1, "chunithm", 250) is None
    store.close()


def test_render_day_without_new_records():
    png = render.render_day("maimai", "p", "2026/09/30", [("크레딧", "2"), ("곡", "6"), ("신기록", "0"),
                                                         ("AP·FC", "0")], [], [], [], 0, None, "15212", None)
    assert png[:4] in (b"RIFF", b"\x89PNG", b"\xff\xd8\xff\xe0")


def test_day_layout_keeps_the_sides_about_as_tall():
    assert render._day_layout(1, 2) == (1, 1)
    assert render._day_layout(0, 40)[0] == 0 and render._day_layout(5, 0)[1] == 0
    left, right = render._day_layout(13, 31)
    assert abs(-(-13 // left) * 142 - -(-31 // right) * 94) < 400


def test_a_chart_played_again_is_one_row():
    from chumai.playlog import Badge, by_chart

    def play(t, title, score, new, lamp=None):
        return PlayRecord(f"2026/09/30 20:{t:02d}", 1, title, "MASTER", score, None, lamp, new, None)

    plays = [play(1, "A", 1_004_000, False), play(2, "A", 1_006_500, True, "FC"), play(3, "B", 1_000_000, False),
             play(4, "A", 1_007_900, True), play(5, "A", 1_007_900, False), play(6, "C", 990_000, False)]
    marks = {plays[1].key: Badge("new", delta=1000), plays[3].key: Badge("new", delta=1400),
             plays[4].key: Badge("tie"), plays[2].key: Badge("best", best=1_002_000)}
    rows = by_chart(plays, marks)
    assert [(r.title, r.score, r.lamp, n) for r, _, n in rows] == [
        ("A", 1_007_900, "FC", 4), ("C", 990_000, None, 1), ("B", 1_000_000, None, 1)]
    assert rows[0][1].kind == "new" and rows[0][1].delta == 2400
    assert rows[1][1] is None and rows[2][1].kind == "best"


def test_render_day_with_new_records_and_the_rest():
    from chumai.b50 import make_entry
    from chumai.playlog import Badge

    entries = [make_entry("chunithm", f"T{i}", "MASTER", "14", 14.0, 1_005_000, None, False) for i in range(14)]
    badges = [Badge("new", delta=100)] * 11 + [Badge("best", best=1_007_000), None, Badge("tie")]
    png = render.render_day("chunithm", "p", "2026/09/30", [("플레이", "20")], entries, badges, [3] + [1] * 13, 11)
    assert png[:4] in (b"RIFF", b"\x89PNG", b"\xff\xd8\xff\xe0")
