from PIL import Image

from chumai import snapshot
from chumai.b50 import make_entry, select_b50


def test_roundtrip(tmp_path):
    jacket = tmp_path / "j.png"
    Image.new("RGB", (4, 4), (255, 0, 0)).save(jacket)
    e1 = make_entry("chunithm", "A", "MASTER", "14", 14.2, 1_008_000, None, False)
    e1.jacket_path = str(jacket)
    e2 = make_entry("chunithm", "B", "EXPERT", "13", 13.1, 1_000_000, "AJ", True)
    b = select_b50("chunithm", "p", [e1, e2], official_rating="16.00", title="t", title_rarity="gold", level="74")
    b.icon = b"icon"
    back = snapshot.load(snapshot.dump(b), tmp_path / "out")
    assert back.username == "p" and back.level == "74" and back.icon == b"icon"
    assert [e.title for e in back.old] == ["A"] and back.new[0].lamp == "AJ"
    assert back.old[0].rating == e1.rating and Image.open(back.old[0].jacket_path).size == (4, 4)
