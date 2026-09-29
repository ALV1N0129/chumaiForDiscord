from chumai.answers import kana_to_hangul, matches
from chumai.storage import LinkStore


def test_titles_ignore_spaces_symbols_and_accents():
    assert matches("aleph 0", ["Aleph-0"])
    assert matches("uiverse", ["U&iVERSE -銀河鸞翔-"])
    assert matches("tuatha de danann", ["Tuatha Dé Danann"])
    assert matches("crossmythos rapsody", ["Crossmythos Rhapsody"])  # a typo


def test_a_long_enough_part_of_the_title():
    assert matches("endy", ["ENDYMION"])
    assert matches("crossmythos", ["Crossmythos Rhapsody"])
    assert matches("千本", ["千本桜"])
    assert not matches("en", ["ENDYMION"])
    assert not matches("the", ["The EmpErroR"])  # too short a share of the title


def test_korean_and_kana_from_the_official_reading():
    reading = ["ノウシヨウサクレツカウル"]  # 脳漿炸裂ガール as the official list writes it
    assert kana_to_hangul(reading[0]) == "노우쇼우사쿠레츠카우루"
    for answer in ("노우쇼사쿠레츠가루", "노쇼사쿠레츠가루", "노우쇼", "のうしょうさくれつがーる"):
        assert matches(answer, ["脳漿炸裂ガール"], reading), answer
    assert matches("센본자쿠라", ["千本桜"], ["センホンサクラ"])
    assert matches("미쿠노쇼시츠", ["初音ミクの消失"], ["ハツネミクノシヨウシツ"])
    assert not matches("뇌장작렬걸", ["脳漿炸裂ガール"], reading)  # a translation: needs /alias
    assert not matches("센본자쿠라", ["脳漿炸裂ガール"], reading)


def test_registered_nicknames(tmp_path):
    store = LinkStore(tmp_path / "t.db")
    assert store.add_alias(1, "chunithm", "脳漿炸裂ガール", "뇌장작렬걸")
    assert not store.add_alias(1, "chunithm", "脳漿炸裂ガール", "뇌장작렬걸")
    assert store.aliases(1, "chunithm", "脳漿炸裂ガール") == ["뇌장작렬걸"]
    assert store.aliases(2, "chunithm", "脳漿炸裂ガール") == []  # per server
    assert matches("뇌장작렬걸", ["脳漿炸裂ガール"], [], store.aliases(1, "chunithm", "脳漿炸裂ガール"))
    assert store.remove_alias(1, "chunithm", "脳漿炸裂ガール", "뇌장작렬걸")
    assert store.aliases(1, "chunithm", "脳漿炸裂ガール") == []
    store.close()
