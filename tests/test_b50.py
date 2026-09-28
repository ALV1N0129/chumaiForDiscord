from fractions import Fraction

from chumai.b50 import make_entry, select_b50
from chumai.render import render_b50


def _entries(n_old: int, n_new: int):
    return [
        make_entry("chunithm", f"Song {i}", "MASTER", "14", 14.0 + (i % 10) / 10, 1_005_000, None, i >= n_old)
        for i in range(n_old + n_new)
    ]


def test_chunithm_b50_split_and_total():
    b = select_b50("chunithm", "tester", _entries(40, 25))
    assert len(b.old) == 30 and len(b.new) == 20
    assert all(not e.is_new for e in b.old) and all(e.is_new for e in b.new)
    assert [e.rating for e in b.old] == sorted((e.rating for e in b.old), reverse=True)
    assert b.total == Fraction(int((b.old_sum + b.new_sum) / 50 * 100), 100)


def test_maimai_b50_total_is_sum():
    entries = [
        make_entry("maimai", "A", "DX Master", "14+", 14.7, 100.5, "AP", True),
        make_entry("maimai", "B", "Re:Master", "14", 14.2, 99.5, None, False),
    ]
    b = select_b50("maimai", "u", entries)
    assert b.total == 330 + 298
    assert b.new[0].score_text == "100.5000%" and b.old[0].rating_text == "298"


def test_render_smoke():
    import io

    from PIL import Image

    from chumai import render

    data = render_b50(select_b50("chunithm", "tester", _entries(40, 25)))
    assert Image.open(io.BytesIO(data)).format == "WEBP"
    assert render.encode(Image.new("RGB", (4, 4)), "png")[:8] == b"\x89PNG\r\n\x1a\n"
    assert render.encode(Image.new("RGB", (4, 4)), "jpeg")[:2] == b"\xff\xd8"
    assert render.filename("b50_maimai") == "b50_maimai.webp"
