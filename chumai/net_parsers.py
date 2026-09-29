"""HTML parsers for CHUNITHM-NET (international) and maimai DX NET (international)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

CHUNITHM_DIFFS = {
    "basic": "BASIC",
    "advanced": "ADVANCED",
    "expert": "EXPERT",
    "master": "MASTER",
    "ultima": "ULTIMA",
    "worldsend": "WORLD'S END",
}

MAIMAI_DIFFS = ["Basic", "Advanced", "Expert", "Master", "Re:Master"]

MAIMAI_LAMPS = {"app": "AP+", "ap": "AP", "fcp": "FC+", "fc": "FC"}


@dataclass
class ChunithmRecord:
    idx: int
    title: str
    difficulty: str
    score: int
    lamp: str | None = None  # "AJC" / "AJ" / "FC" (only the record pages show it)


@dataclass
class MaimaiRecord:
    title: str
    genre: str
    difficulty: str  # Tachi naming: "Master", "DX Master", ...
    level: str
    achievement: float
    lamp: str | None


@dataclass
class PlayerInfo:
    name: str
    rating: str | None
    icon_url: str | None = None  # CHUNITHM character / maimai icon
    title: str | None = None  # 칭호
    title_rarity: str | None = None  # normal, bronze, silver, gold, platina, rainbow, ...
    plate_url: str | None = None  # nameplate
    level: str | None = None


def _style_url(style: str) -> str | None:
    m = re.search(r"url\(['\"]?([^'\")]+)", style or "")
    return m.group(1) if m else None


def _soup(html: str | bytes) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _text(node: Tag | None) -> str:
    return node.get_text(strip=True) if node is not None else ""


# ---------------------------------------------------------------- CHUNITHM


def parse_chunithm_player(html: str | bytes) -> PlayerInfo:
    soup = _soup(html)
    name = _text(soup.select_one(".player_name_in"))
    digits = ""
    for img in soup.select(".player_rating_num_block img"):
        part = str(img.get("src", "")).rsplit("_", 1)[-1].split(".")[0]
        digits += "." if part == "comma" else part[-1:]
    info = PlayerInfo(name=name, rating=digits or None)
    info.level = _text(soup.select_one(".player_lv")) or None
    chara = soup.select_one(".player_chara img")
    if chara is not None and chara.get("src"):
        info.icon_url = str(chara["src"])
    for honor in soup.select(".player_honor_short"):
        bg = _style_url(str(honor.get("style", ""))) or ""
        text = _text(honor.select_one(".player_honor_text span"))
        if text and "honor_bg_" in bg:
            info.title = text
            info.title_rarity = bg.rsplit("honor_bg_", 1)[1].split(".")[0]
            break
    return info


def parse_chunithm_nameplate(html: str | bytes) -> str | None:
    """Nameplate image URL from /mobile/collection/customise/."""
    img = _soup(html).select_one(".nameplate_now img")
    return str(img["src"]) if img is not None and img.get("src") else None


def parse_chunithm_rating_list(html: str | bytes) -> list[ChunithmRecord]:
    """Parse ratingDetailBest / ratingDetailRecent pages."""
    records = []
    for form in _soup(html).select("form"):
        box = form.select_one(".musiclist_box")
        score_el = form.select_one(".play_musicdata_highscore .text_b")
        idx_el = form.select_one("input[name=idx]")
        if box is None or score_el is None or idx_el is None:
            continue
        diff = next(
            (CHUNITHM_DIFFS[c[3:]] for c in box.get("class", []) if c.startswith("bg_") and c[3:] in CHUNITHM_DIFFS),
            None,
        )
        if diff is None:
            continue
        records.append(
            ChunithmRecord(
                idx=int(str(idx_el.get("value"))),
                title=_text(form.select_one(".music_title, .musiclist_worldsend_title")),
                difficulty=diff,
                score=int(_text(score_el).replace(",", "")),
            )
        )
    return records


CHUNITHM_LAMP_ICONS = (("alljusticecritical", "AJC"), ("alljustice", "AJ"), ("fullcombo", "FC"))
_IDX = re.compile(r'<input[^>]*name="idx"[^>]*value="(\d+)"|<input[^>]*value="(\d+)"[^>]*name="idx"')


def parse_chunithm_music_ids(html: str | bytes) -> set[int]:
    """Music ids of every song on a record page (musicGenre/send<Difficulty>), played or not: the
    songs of that difficulty in the player's region. String search, like parse_chunithm_lamps."""
    text = html.decode("utf-8", "replace") if isinstance(html, bytes) else html
    return {int(m.group(1) or m.group(2)) for m in _IDX.finditer(text)}


def parse_chunithm_lamps(html: str | bytes) -> dict[int, str]:
    """{music idx: "AJC"/"AJ"/"FC"} from a record page (musicGenre/send<Difficulty>).

    These pages list every song, so they are read with plain string searches (one song's <form>
    at a time) instead of a parsed tree, which would take tens of MB on a small host."""
    text = html.decode("utf-8", "replace") if isinstance(html, bytes) else html
    lamps = {}
    for chunk in text.split("<form")[1:]:
        m = _IDX.search(chunk)
        if not m:
            continue
        for name, lamp in CHUNITHM_LAMP_ICONS:
            if name in chunk:
                lamps[int(m.group(1) or m.group(2))] = lamp
                break
    return lamps


# ------------------------------------------------------------------ maimai


def parse_maimai_player(html: str | bytes) -> PlayerInfo:
    soup = _soup(html)
    rating = _text(soup.select_one(".rating_block")) or None
    info = PlayerInfo(name=_text(soup.select_one(".name_block")), rating=rating)
    for img in soup.select("img"):
        src = str(img.get("src", ""))
        if "/img/Icon/" in src and info.icon_url is None:
            info.icon_url = src
        elif "/img/NamePlate/" in src and info.plate_url is None:
            info.plate_url = src
    trophy = soup.select_one("[class*=trophy_]")
    if trophy is not None:
        text = _text(trophy.select_one("span") or trophy)
        rarity = next((c[7:] for c in trophy.get("class", []) if c.startswith("trophy_") and c != "trophy_block"),
                      None)
        if text:
            info.title, info.title_rarity = text, (rarity or "normal").lower()
    return info


def _maimai_is_std(row: Tag) -> bool:
    row_id = str(row.get("id", ""))
    if row_id:
        return "sta_" in row_id
    icon = row.select_one(".music_kind_icon")
    return icon is not None and "_standard" in str(icon.get("src", ""))


def parse_maimai_scores(html: str | bytes, diff_index: int,
                        seen: dict[str, set[str]] | None = None) -> list[MaimaiRecord]:
    """Parse /maimai-mobile/record/musicGenre/search/?genre=99&diff=N.

    `seen` collects every song on the page, played or not ({difficulty: {title}}): the charts in
    the player's region."""
    base_diff = MAIMAI_DIFFS[diff_index]
    records = []
    genre = ""
    for row in _soup(html).select(".main_wrapper.t_c .m_15"):
        classes = set(row.get("class", []))
        if "screw_block" in classes:
            genre = _text(row)
            continue
        if not {"w_450", "p_r", "f_0"} <= classes:
            continue
        difficulty = base_diff if _maimai_is_std(row) else f"DX {base_diff}"
        if seen is not None:
            seen.setdefault(difficulty, set()).add(_text(row.select_one(".music_name_block")))
        score_blocks = row.select(".music_score_block")
        if not score_blocks:
            continue  # not played
        try:
            achievement = float(_text(score_blocks[0]).rstrip("%"))
        except ValueError:
            continue

        lamp = None
        for img in row.select("img"):
            m = re.search(r"music_icon_([a-z]+)\.png", str(img.get("src", "")))
            if m and m.group(1) in MAIMAI_LAMPS:
                lamp = MAIMAI_LAMPS[m.group(1)]
                break

        records.append(
            MaimaiRecord(
                title=_text(row.select_one(".music_name_block")),
                genre=genre,
                difficulty=difficulty,
                level=_text(row.select_one(".music_lv_block")),
                achievement=achievement,
                lamp=lamp,
            )
        )
    return records


def parse_error_message(html: str | bytes) -> str | None:
    soup = _soup(html)
    for sel in (".block.text_l .font_small", ".container_red", ".p_5.f_14"):
        nodes = soup.select(sel)
        if nodes:
            return " ".join(_text(n) for n in nodes if _text(n))[:300] or None
    return None


# --------------------------------------------------------------- play logs


@dataclass
class PlayRecord:
    date: str  # "YYYY/MM/DD HH:MM" (JST) — sorts correctly as a string
    track: int
    title: str
    difficulty: str  # CHUNITHM: "MASTER"...; maimai: Tachi naming ("DX Master"...)
    score: float  # CHUNITHM score / maimai achievement %
    rank: str | None
    lamp: str | None
    new_record: bool
    jacket_url: str | None
    genre: str = ""

    @property
    def key(self) -> str:
        return f"{self.date}#{self.track:02d}"


def _img_name(img: Tag | None, attr: str = "src") -> str:
    if img is None:
        return ""
    src = str(img.get(attr) or img.get("src") or "")
    return src.split("?")[0].rsplit("/", 1)[-1].rsplit(".", 1)[0]


def parse_chunithm_playlog(html: str | bytes) -> list[PlayRecord]:
    """Parse /mobile/record/playlog (newest first)."""
    out = []
    for row in _soup(html).select(".frame02.w400"):
        date = _text(row.select_one(".play_datalist_date"))
        track_txt = _text(row.select_one(".play_track_text"))
        score_txt = _text(row.select_one(".play_musicdata_score_text"))
        if not date or not track_txt or not score_txt:
            continue
        diff = _img_name(row.select_one(".play_track_result img")).split("_")[-1]
        icons = [_img_name(i) for i in row.select(".play_musicdata_icon img")]
        lamp = None
        for name, label in (("alljusticecritical", "AJC"), ("alljustice", "AJ"), ("fullcombo", "FC")):
            if any(name in i for i in icons):
                lamp = label
                break
        jacket = row.select_one(".play_jacket_img img")
        out.append(
            PlayRecord(
                date=date,
                track=int(re.sub(r"\D", "", track_txt) or 0),
                title=_text(row.select_one(".play_musicdata_title")),
                difficulty=CHUNITHM_DIFFS.get(diff, diff.upper()),
                score=int(score_txt.replace(",", "")),
                rank=None,
                lamp=lamp,
                new_record=row.select_one(".play_musicdata_score_img") is not None,
                jacket_url=str(jacket.get("data-original") or jacket.get("src")) if jacket else None,
            )
        )
    return out


MAIMAI_PLAYLOG_LAMPS = {"fc": "FC", "fcplus": "FC+", "ap": "AP", "applus": "AP+"}


def parse_maimai_playlog(html: str | bytes) -> list[PlayRecord]:
    """Parse /maimai-mobile/record/ (newest first)."""
    out = []
    for row in _soup(html).select(".main_wrapper .p_10.t_l.f_0.v_b"):
        sub = row.select_one(".playlog_top_container .sub_title")
        spans = [s for s in sub.find_all(recursive=False)] if sub else []
        track_txt = _text(spans[0]) if spans else ""
        date = ""
        for s in spans:
            m = re.search(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}", _text(s))
            if m:
                date = m.group(0)
        ach = row.select_one(".playlog_achievement_txt")
        if not date or ach is None:
            continue
        try:
            achievement = float(re.sub(r"[^\d.]", "", _text(ach)))
        except ValueError:
            continue
        diff_name = _img_name(row.select_one("img.playlog_diff")).split("_")[-1].lower()
        base = {"basic": "Basic", "advanced": "Advanced", "expert": "Expert", "master": "Master",
                "remaster": "Re:Master", "utage": "UTAGE"}.get(diff_name)
        if base is None:
            continue
        kind = row.select_one(".playlog_music_kind_icon")
        is_std = kind is not None and "_standard" in str(kind.get("src", ""))
        title_el = row.select_one(".basic_block.break") or row.select_one(".m_5.p_5.f_13")
        title = ""
        if title_el is not None:
            texts = [t.strip() for t in title_el.find_all(string=True, recursive=False) if t.strip()]
            title = texts[-1] if texts else _text(title_el)
        rank = _img_name(row.select_one("img.playlog_scorerank")).replace("plus", "+").upper() or None
        stamps = [_img_name(i) for i in row.select(".playlog_result_innerblock > img")]
        jacket = row.select_one(".music_img")
        out.append(
            PlayRecord(
                date=date,
                track=int(re.sub(r"\D", "", track_txt) or 0),
                title=title,
                difficulty=base if is_std or base == "UTAGE" else f"DX {base}",
                score=achievement,
                rank=rank,
                lamp=MAIMAI_PLAYLOG_LAMPS.get(stamps[0]) if stamps else None,
                new_record=row.select_one("img.playlog_achievement_newrecord") is not None,
                jacket_url=str(jacket.get("src")) if jacket is not None else None,
            )
        )
    return out


def group_credits(records: list[PlayRecord]) -> list[list[PlayRecord]]:
    """Split plays (any order) into credits, oldest first. A credit restarts at TRACK 1."""
    credits: list[list[PlayRecord]] = []
    for r in sorted(records, key=lambda r: r.key):
        if not credits or r.track <= credits[-1][-1].track:
            credits.append([])
        credits[-1].append(r)
    return credits
