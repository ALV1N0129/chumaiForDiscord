"""Answer checking for the guessing games: short answers, Korean and registered nicknames.

- Spaces and symbols don't matter ("aleph0" = "Aleph-0").
- A long enough part of the title counts ("endy" for ENDYMION, "crossmythos").
- Korean: the official song lists give each title's reading in katakana (without voicing marks,
  e.g. 脳漿炸裂ガール -> ノウシヨウサクレツカウル). It is written in Hangul and compared loosely, so
  "노우쇼우사쿠레츠가루" or "뇌쇼사쿠레츠가루" match; consonants that the reading can't tell apart
  (가/카, 바/파/하, 사/자) and similar vowels count as the same.
- Kanji titles also in their Korean reading: 脳漿炸裂ガール -> 뇌장작렬가루, 千本桜 -> 천본앵, with の as
  의 as well (初音ミクの消失 -> 초음미쿠의소실). The readings of the kanji in song titles come from
  Unicode's Unihan database (kHangul; Japanese simplified forms mapped by hand), in
  assets/hanja_ko.json.
- Korean names in assets/titles_ko.tsv, written by hand for nearly every title: Latin titles as read
  (ENDYMION -> 엔디미온), katakana titles as said in Korean (ヴァンパイア -> 뱀파이어) and Japanese titles
  translated (夜に駆ける -> 밤을 달리다).
- Registered nicknames (/alias) count like titles.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import time
import unicodedata
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

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
    # the start of a title is a natural short form; elsewhere it must be a fair share of it
    return long_enough and (k.startswith(a) or (a in k and len(a) >= min_part * len(k)))


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


# consonants the readings can't tell apart (no voicing marks; 란/난 as the kanji readings go), and
# vowels written either way
_LEAD_FOLD = {"ㄹ": "ㄴ", "ㄲ": "ㄱ", "ㅋ": "ㄱ", "ㄸ": "ㄷ", "ㅌ": "ㄷ", "ㅃ": "ㅂ", "ㅍ": "ㅂ", "ㅎ": "ㅂ",
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


@lru_cache(maxsize=1)
def _hanja() -> dict[str, str]:
    return json.loads((Path(__file__).parent / "assets" / "hanja_ko.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _pronunciations() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in (Path(__file__).parent / "assets" / "titles_ko.tsv").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("# "):  # a comment (titles like "#FairyJoke" start with # too)
            title, *names = line.split("\t")
            out.setdefault(fold(title), []).extend(n for n in names if n)
    return out


def pronunciations(title: str) -> list[str]:
    """Korean pronunciations of a Latin-alphabet title (assets/titles_ko.tsv)."""
    return _pronunciations().get(fold(title), [])


def korean_readings(title: str) -> list[str]:
    """A title with kanji in their Korean reading and kana in Hangul, as it and with の as 의
    ([] when the title has no kanji, or a kanji without a reading)."""
    text = fold(title)
    table = _hanja()
    if not any(unicodedata.name(c, "").startswith("CJK UNIFIED") for c in text):
        return []
    out = []
    for no in ("노", "의"):
        parts, kana = [], ""
        for ch in text + " ":
            if _KANA.match(ch) or ch == "ー":
                kana += ch
                continue
            if kana:
                parts.append(no.join(kana_to_hangul(k) for k in kana.split("の")))
                kana = ""
            if unicodedata.name(ch, "").startswith("CJK UNIFIED"):
                if ch not in table:
                    return []
                parts.append(table[ch])
            elif ch != " ":
                parts.append(ch)
        out.append("".join(parts))
    return list(dict.fromkeys(out))


# Community nicknames collected by GCM-bot (https://github.com/lomotos10/GCM-bot): Korean for maimai,
# English/romaji for both. Downloaded when the bot runs and kept in the cache folder, not shipped here.
COMMUNITY_URL = "https://raw.githubusercontent.com/lomotos10/GCM-bot/main/data/aliases/{lang}/{name}.tsv"
COMMUNITY_FILES = {"chunithm": [("en", "chuni")], "maimai": [("ko", "maimai"), ("en", "maimai")]}
COMMUNITY_REFRESH = 7 * 24 * 60 * 60
_community: dict[str, dict[str, list[str]]] = {"chunithm": {}, "maimai": {}}


def load_community(game: str, text: str) -> None:
    """Add the nicknames of a GCM-bot alias file (title<TAB>nickname<TAB>...)."""
    table = _community[game]
    for line in text.splitlines():
        title, *names = line.split("\t")
        names = [n.strip() for n in names if n.strip()]
        if title.strip() and names:
            found = table.setdefault(fold(title), [])
            found.extend(n for n in names if n not in found)


def community_aliases(game: str, title: str) -> list[str]:
    return _community.get(game, {}).get(fold(title), [])


async def update_community(cache_dir: str | Path) -> None:
    """Download the community nickname files (weekly) and load them; keeps the cached copies (or
    nothing) when GitHub can't be reached."""
    import aiohttp

    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
        for game, files in COMMUNITY_FILES.items():
            _community[game] = {}
            for lang, name in files:
                path = cache / f"{lang}_{name}.tsv"
                if not path.exists() or time.time() - path.stat().st_mtime > COMMUNITY_REFRESH:
                    try:
                        async with s.get(COMMUNITY_URL.format(lang=lang, name=name)) as resp:
                            resp.raise_for_status()
                            path.write_text(await resp.text(encoding="utf-8"), encoding="utf-8")
                    except Exception as e:
                        log.warning("could not download community nicknames %s/%s: %s", lang, name, e)
                if path.exists():
                    load_community(game, path.read_text(encoding="utf-8"))
    log.info("community nicknames: %s", {g: len(t) for g, t in _community.items()})


def initials(name: str) -> str:
    """The first syllable of each word of a Korean name, the usual short form (프리덤 다이브 -> 프다,
    월드 뱅퀴셔 -> 월뱅); "" for a single word."""
    words = [w for w in re.split(r"[\s\-_:~・]+", unicodedata.normalize("NFKC", name)) if w]
    if len(words) < 2 or not all(_HANGUL.match(w) for w in words):
        return ""
    return "".join(w[0] for w in words)


def matches(answer: str, titles: list[str], readings: list[str] = (), aliases: list[str] = ()) -> bool:
    """Whether `answer` names the song with these titles, official readings and nicknames."""
    a = fold(answer)
    if not a:
        return False
    spoken_titles = [p for t in titles for p in pronunciations(t)]
    if any(_close(a, fold(k), FUZZY) for k in [*titles, *aliases, *spoken_titles]):
        return True
    if any(a == initials(p) for p in [*spoken_titles, *aliases]):  # exactly, it's short
        return True
    # a title in kana is its own reading (not every song has one in the official lists)
    readings = [*readings, *(t for t in titles if _KANA.search(t))]
    if _HANGUL.search(a):
        key = hangul_key(a)
        spoken = [hangul_key(kana_to_hangul(fold(r))) for r in readings]
        spoken += [hangul_key(k) for t in titles for k in korean_readings(t)]
        spoken += [hangul_key(fold(p)) for p in [*spoken_titles, *aliases] if _HANGUL.search(p)]
        # compared as letters (ㄴㅗㅅㅛ), about twice as long as syllables: a smaller share will do
        return any(_close(key, k, FUZZY_KOREAN, MIN_PART * 0.8) for k in spoken)
    if _KANA.search(a):
        return any(_close(kana_fold(a), kana_fold(r), FUZZY) for r in readings)
    return False
