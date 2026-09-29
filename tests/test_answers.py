from chumai.answers import kana_to_hangul, korean_readings, matches
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
    assert not matches("센본자쿠라", ["脳漿炸裂ガール"], reading)


def test_korean_reading_of_kanji_titles():
    assert korean_readings("千本桜") == ["천본앵"]
    assert korean_readings("初音ミクの消失") == ["초음미쿠노소실", "초음미쿠의소실"]
    assert korean_readings("ENDYMION") == []
    assert matches("뇌장작렬걸", ["脳漿炸裂ガール"])
    assert matches("천본앵", ["千本桜"])
    assert matches("미쿠의 소실", ["初音ミクの消失"])
    assert matches("은하란상", ["U&iVERSE -銀河鸞翔-"])  # 란 / 난
    assert matches("혼돈", ["混沌を越えし我らが神聖なる調律主を讃えよ"])  # the start of a long title
    assert not matches("천본앵", ["脳漿炸裂ガール"])


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


def test_korean_pronunciation_of_latin_titles():
    from chumai.answers import _pronunciations, fold
    assert matches("엔디미온", ["ENDYMION"])
    assert matches("알레프", ["Aleph-0"])
    assert matches("오샤마", ["Oshama Scramble!"])
    assert not matches("엔디미온", ["Aleph-0"])
    # every line of the file is a title and at least one reading
    for title, names in _pronunciations().items():
        assert title == fold(title) and names and all(n.strip() for n in names)
    assert matches("페어리조크", ["#FairyJoke"])  # a title starting with # isn't a comment


def test_katakana_titles_as_said_in_korean():
    assert matches("뱀파이어", ["ヴァンパイア"])  # the reading would give 반파이아
    assert matches("월드 이즈 마인", ["ワールドイズマイン"])
    assert matches("세카이노오와리", ["せかいのおわり"])  # a kana title is its own reading
    assert not matches("멜트", ["ヴァンパイア"])


def test_japanese_titles_translated():
    assert matches("밤을 달리다", ["夜に駆ける"])
    assert matches("잔혹한 천사의 테제", ["残酷な天使のテーゼ"])
    assert matches("네가 모르는 이야기", ["君の知らない物語"])
    assert not matches("천체관측", ["紅蓮華"])
