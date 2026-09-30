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


def test_every_play_has_its_own_slot():
    from chumai.playlog import Badge, day_timeline

    def play(t, track, title, score, new, lamp=None):
        return PlayRecord(f"2026/09/30 20:{t:02d}", track, title, "MASTER", score, None, lamp, new, None)

    plays = [play(1, 1, "A", 1_004_000, False), play(1, 2, "A", 1_006_500, True, "FC"),
             play(1, 3, "A", 1_005_000, False), play(1, 4, "B", 1_000_000, False),
             play(9, 1, "A", 1_007_900, True)]
    marks = {plays[1].key: Badge("new", delta=500, gain=Fraction(3, 1000)), plays[4].key: Badge("new", first=False)}
    credits, steps = day_timeline(plays, marks)
    assert [time for time, _ in credits] == ["20:01", "20:09"]
    assert [(d.play.score, d.new, d.count, d.gain, d.delta) for d in credits[0][1]] == [
        (1_004_000, False, 1, 0, None), (1_006_500, True, 1, 0.003, 500), (1_005_000, False, 1, 0, None),
        (1_000_000, False, 1, 0, None)]
    assert steps == [(0, 0.375, 0.003, 1)]


def test_render_day_timeline():
    from chumai.b50 import make_entry

    def slot(score, new, count=1, gain=0.0):
        return render.DaySlot(make_entry("chunithm", "T", "MASTER", "14", 14.0, score, None, False), new, count,
                              gain)

    credits = [render.DayCredit("18:00", [slot(1_005_000, True, 1, 0.004), slot(1_000_000, False, 3)]),
               render.DayCredit("18:14", [slot(1_007_000, False)])]
    png = render.render_day("chunithm", "p", "2026/09/30", [("플레이", "5")], credits, [(0, 0.25, 0.004, 0)], 16.97,
                            None, "16.97", "16.96")
    assert png[:4] in (b"RIFF", b"\x89PNG", b"\xff\xd8\xff\xe0")


def test_today_turns_over_at_4am_japan_time():
    import datetime

    from chumai.bot import JST, today

    assert str(today(datetime.datetime(2026, 10, 1, 3, 59, tzinfo=JST))) == "2026-09-30"
    assert str(today(datetime.datetime(2026, 10, 1, 4, 0, tzinfo=JST))) == "2026-10-01"
    # 20:00 UTC is 5am the next day in Japan
    assert str(today(datetime.datetime(2026, 9, 30, 20, 0, tzinfo=datetime.timezone.utc))) == "2026-10-01"
