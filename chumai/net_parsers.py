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
    return PlayerInfo(name=name, rating=digits or None)


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


# ------------------------------------------------------------------ maimai


def parse_maimai_player(html: str | bytes) -> PlayerInfo:
    soup = _soup(html)
    rating = _text(soup.select_one(".rating_block")) or None
    return PlayerInfo(name=_text(soup.select_one(".name_block")), rating=rating)


def _maimai_is_std(row: Tag) -> bool:
    row_id = str(row.get("id", ""))
    if row_id:
        return "sta_" in row_id
    icon = row.select_one(".music_kind_icon")
    return icon is not None and "_standard" in str(icon.get("src", ""))


def parse_maimai_scores(html: str | bytes, diff_index: int) -> list[MaimaiRecord]:
    """Parse /maimai-mobile/record/musicGenre/search/?genre=99&diff=N."""
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
                difficulty=base_diff if _maimai_is_std(row) else f"DX {base_diff}",
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
