"""Answer checking for the guessing games: short answers, Korean and registered nicknames.

- Spaces and symbols don't matter ("aleph0" = "Aleph-0").
- A long enough part of the title counts ("endy" for ENDYMION, "crossmythos").
- Korean: the official song lists give each title's reading in katakana (without voicing marks,
  e.g. 脳漿炸裂ガール -> ノウシヨウサクレツカウル). It is written in Hangul and compared loosely, so
  "노우쇼우사쿠레츠가루" or "뇌쇼사쿠레츠가루" match; consonants that the reading can't tell apart
  (가/카, 바/파/하, 사/자) and similar vowels count as the same.
- Registered nicknames (/alias) count like titles.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

FUZZY = 0.85  # a typo or two in a title
FUZZY_KOREAN = 0.8  # Hangul from a reading is rougher
MIN_PART = 0.25  # a part of a title must be at least this share of it


def fold(text: str) -> str:
    """Lower case, full-width folded, without spaces, symbols or accents (Dé = de, ガ = カ)."""
    text = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text).lower())
    text = unicodedata.normalize("NFC", "".join(ch for ch in text if not unicodedata.combining(ch)))
    return "".join(ch for ch in text if ch.isalnum())


def _is_wide(ch: str) -> bool:
    return ord(ch) >= 0x2E80  # kana, kanji, Hangul: one character says a lot


def _close(a: str, k: str, fuzzy: float, min_part: float = MIN_PART) -> bool:
    """Same, nearly the same, or a long enough part of k."""
    if not a or not k:
        return False
    if a == k or difflib.SequenceMatcher(None, a, k).ratio() >= fuzzy:
        return True
    long_enough = len(a) >= 4 or (len(a) >= 2 and any(_is_wide(c) for c in a))
    return long_enough and a in k and len(a) >= min_part * len(k)


# --------------------------------------------------------------- kana -> Hangul

_ROWS = {
    "": "아이우에오", "k": "카키쿠케코", "s": "사시스세소", "t": "타치츠테토", "n": "나니누네노",
    "h": "하히후헤호", "m": "마미무메모", "y": "야 유 요", "r": "라리루레로", "w": "와   오",
}
_KANA_ROWS = {
    "": "アイウエオ", "k": "カキクケコ", "s": "サシスセソ", "t": "タチツテト", "n": "ナニヌネノ",
    "h": "ハヒフヘホ", "m": "マミムメモ", "y": "ヤ ユ ヨ", "r": "ラリルレロ", "w": "ワ   ヲ",
}
KANA = {k: h for row in _ROWS for k, h in zip(_KANA_ROWS[row], _ROWS[row]) if k != " "}
KANA.update({"ヴ": "부", "ヰ": "이", "ヱ": "에"})
_SMALL = {"ャ": "ㅑ", "ュ": "ㅠ", "ョ": "ㅛ", "ァ": "ㅏ", "ィ": "ㅣ", "ゥ": "ㅜ", "ェ": "ㅔ", "ォ": "ㅗ"}
_SMALL_FULL = {"ャ": "ヤ", "ュ": "ユ", "ョ": "ヨ", "ァ": "ア", "ィ": "イ", "ゥ": "ウ", "ェ": "エ", "ォ": "オ",
               "ヵ": "カ", "ヶ": "ケ", "ヮ": "ワ"}

_L = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_V = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_T = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"


def _split(syllable: str) -> tuple[str, str, str]:
    i = ord(syllable) - 0xAC00
    return _L[i // 588], _V[i % 588 // 28], _T[i % 28].strip()


def _join(lead: str, vowel: str, tail: str = "") -> str:
    return chr(0xAC00 + (_L.index(lead) * 21 + _V.index(vowel)) * 28 + _T.index(tail or " "))


def kana_to_hangul(reading: str) -> str:
    """Katakana (or hiragana) written in Hangul, roughly; other characters are kept."""
    text = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in unicodedata.normalize("NFKC", reading))
    text = unicodedata.normalize("NFKD", text).replace("\u3099", "").replace("\u309a", "")  # voicing marks
    out: list[str] = []
    for ch in text:
        if ch in _SMALL and out and "가" <= out[-1] <= "힣":
            lead, _, _ = _split(out[-1])  # キャ -> 캬, フォ -> 포-ish
            out[-1] = _join(lead, _SMALL[ch])
        elif ch in ("ン", "ッ") and out and "가" <= out[-1] <= "힣":
            lead, vowel, tail = _split(out[-1])
            if not tail:
                out[-1] = _join(lead, vowel, "ㄴ" if ch == "ン" else "ㅅ")
        elif ch in "ヤユヨ" and out and "가" <= out[-1] <= "힣" and _split(out[-1])[1] == "ㅣ" \
                and _split(out[-1])[0] != "ㅇ" and not _split(out[-1])[2]:
            # the readings write small ャュョ full size (ショウ -> シヨウ): シヨ is almost always ショ
            out[-1] = _join(_split(out[-1])[0], _SMALL["ャュョ"["ヤユヨ".index(ch)]])
        elif ch == "ー":
            continue
        else:
            ch = _SMALL_FULL.get(ch, ch)
            out.append(KANA.get(ch, ch))
    return "".join(out)


# consonants the readings can't tell apart (no voicing marks), and vowels written either way
_LEAD_FOLD = {"ㄲ": "ㄱ", "ㅋ": "ㄱ", "ㄸ": "ㄷ", "ㅌ": "ㄷ", "ㅃ": "ㅂ", "ㅍ": "ㅂ", "ㅎ": "ㅂ",
              "ㅆ": "ㅅ", "ㅈ": "ㅅ", "ㅉ": "ㅅ", "ㅊ": "ㅅ"}
_VOWEL_FOLD = {"ㅐ": "ㅔ", "ㅒ": "ㅖ", "ㅓ": "ㅗ", "ㅕ": "ㅛ", "ㅡ": "ㅜ", "ㅚ": "ㅔ", "ㅙ": "ㅔ", "ㅞ": "ㅔ",
               "ㅢ": "ㅣ", "ㅟ": "ㅣ", "ㅝ": "ㅗ"}


def hangul_key(text: str) -> str:
    """Hangul as folded letters for loose comparison: 센본자쿠라 and 센혼사쿠라 come out the same.
    Final consonants other than ㄴ/ㅁ/ㅇ (all as ㄴ) are dropped, ㅇ before a vowel is silent and long
    vowels (오우, 에이) are one."""
    out = []
    prev = ""  # the last vowel, to drop the long vowel of 오우 / 에이 (쇼우 = 쇼)
    for ch in text:
        if "가" <= ch <= "힣":
            lead, vowel, tail = _split(ch)
            lead = _LEAD_FOLD.get(lead, lead)
            vowel = _VOWEL_FOLD.get(vowel, vowel)
            if lead == "ㅇ" and not tail and (vowel, prev) in (("ㅜ", "ㅗ"), ("ㅜ", "ㅛ"), ("ㅣ", "ㅔ")):
                continue
            out.append(("" if lead == "ㅇ" else lead) + vowel)
            prev = "" if tail else vowel
            if tail in ("ㄴ", "ㅁ", "ㅇ"):
                out.append("ㄴ")
        else:
            out.append(ch)
            prev = ""
    return "".join(out)


_HANGUL = re.compile("[가-힣]")
_KANA = re.compile("[ぁ-ゖァ-ヺ]")


def kana_fold(text: str) -> str:
    """Kana the way the official readings write it: katakana, no voicing marks, small kana full
    size, no ー (ノウショウ -> ノウシヨウ, がーる -> カル)."""
    text = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in fold(text))
    text = unicodedata.normalize("NFKD", text).replace("\u3099", "").replace("\u309a", "")
    return "".join(_SMALL_FULL.get(c, c) for c in text if c != "ー")


def matches(answer: str, titles: list[str], readings: list[str] = (), aliases: list[str] = ()) -> bool:
    """Whether `answer` names the song with these titles, official readings and nicknames."""
    a = fold(answer)
    if not a:
        return False
    if any(_close(a, fold(k), FUZZY) for k in [*titles, *aliases]):
        return True
    if _HANGUL.search(a):
        key = hangul_key(a)
        # compared as letters (ㄴㅗㅅㅛ), about twice as long as syllables: a smaller share will do
        return any(_close(key, hangul_key(kana_to_hangul(fold(r))), FUZZY_KOREAN, MIN_PART * 0.8) for r in readings)
    if _KANA.search(a):
        return any(_close(kana_fold(a), kana_fold(r), FUZZY) for r in readings)
    return False
