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
                                                         ("AP·FC", "0")], [], [], 0, None, "15212", None)
    assert png[:4] in (b"RIFF", b"\x89PNG", b"\xff\xd8\xff\xe0")
