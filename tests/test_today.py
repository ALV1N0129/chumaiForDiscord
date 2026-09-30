from fractions import Fraction

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


def test_render_day_without_plays():
    png = render.render_day("maimai", "p", "2026/09/30", [("크레딧", "0")], [], [], None, None, "15212", None)
    assert png[:4] in (b"RIFF", b"\x89PNG", b"\xff\xd8\xff\xe0")


def test_plays_of_a_chart_in_a_row_are_one_slot():
    from chumai.playlog import Badge, day_timeline

    def play(t, track, title, score, new, lamp=None):
        return PlayRecord(f"2026/09/30 20:{t:02d}", track, title, "MASTER", score, None, lamp, new, None)

    plays = [play(1, 1, "A", 1_004_000, False), play(1, 2, "A", 1_006_500, True, "FC"),
             play(1, 3, "A", 1_005_000, False), play(1, 4, "B", 1_000_000, False),
             play(9, 1, "A", 1_007_900, True)]
    marks = {plays[1].key: Badge("new", gain=Fraction(3, 1000)), plays[4].key: Badge("new")}
    credits, steps = day_timeline(plays, marks)
    assert [time for time, _ in credits] == ["20:01", "20:09"]
    assert [(r.title, r.score, r.lamp, new, n) for r, new, n in credits[0][1]] == [
        ("A", 1_006_500, "FC", True, 3), ("B", 1_000_000, None, False, 1)]
    assert steps == [(0, 0.375, 0.003)]


def test_render_day_timeline():
    from chumai.b50 import make_entry

    def slot(score, new, count=1):
        return render.DaySlot(make_entry("chunithm", "T", "MASTER", "14", 14.0, score, None, False), new, count)

    credits = [render.DayCredit("18:00", [slot(1_005_000, True), slot(1_000_000, False, 3)]),
               render.DayCredit("18:14", [slot(1_007_000, False)])]
    png = render.render_day("chunithm", "p", "2026/09/30", [("플레이", "5")], credits, [(0, 0.25, 0.004)], 16.97,
                            None, "16.97", "16.96")
    assert png[:4] in (b"RIFF", b"\x89PNG", b"\xff\xd8\xff\xe0")
