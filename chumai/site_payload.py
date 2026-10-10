"""maimai DX NET pages → the upload the mai records site (mai.alv1n.fyi) takes.

The same parsing as the site's bookmarklet (bookmarklet/main.ts there), so the site matches songs the
same way whichever of the two sent the records. The payload is short lists, not objects:

    chart: [title, type (0 STD / 1 DX), difficulty (0 BASIC … 4 Re:MASTER), level, artist or None, score or None]
    score: [achievement × 10000, DX score, DX max, combo code, sync code]
    play:  [time (ISO, UTC), track, title, type, difficulty, achievement, DX score, DX max, combo, sync]
"""

from __future__ import annotations

import asyncio
import datetime
import re
import unicodedata
from urllib.parse import quote

from bs4 import BeautifulSoup, Tag

PAYLOAD_VERSION = 1
DIFFICULTY_NAMES = ["BASIC", "ADVANCED", "EXPERT", "MASTER", "Re:MASTER"]
REQUEST_INTERVAL = 0.3  # seconds between NET pages, like the bookmarklet

COMBO_CODES = [None, "FULL COMBO", "FULL COMBO+", "ALL PERFECT", "ALL PERFECT+"]
SYNC_CODES = [None, "SYNC PLAY", "FULL SYNC", "FULL SYNC+", "FULL SYNC DX", "FULL SYNC DX+"]

COMBO_ICONS = {
    "music_icon_fc": "FULL COMBO", "music_icon_fcp": "FULL COMBO+", "music_icon_ap": "ALL PERFECT",
    "music_icon_app": "ALL PERFECT+", "fc": "FULL COMBO", "fcplus": "FULL COMBO+", "ap": "ALL PERFECT",
    "applus": "ALL PERFECT+",
}
SYNC_ICONS = {
    "music_icon_sync": "SYNC PLAY", "music_icon_fs": "FULL SYNC", "music_icon_fsp": "FULL SYNC+",
    "music_icon_fdx": "FULL SYNC DX", "music_icon_fdxp": "FULL SYNC DX+", "sync": "SYNC PLAY", "fs": "FULL SYNC",
    "fsplus": "FULL SYNC+", "fsd": "FULL SYNC DX", "fdx": "FULL SYNC DX", "fsdplus": "FULL SYNC DX+",
    "fdxplus": "FULL SYNC DX+",
}
DISPLAY_LEVELS = {"1", "2", "3", "4", "5", "6", *(f"{n}{p}" for n in range(7, 15) for p in ("", "+")), "15"}


class PageError(Exception):
    """A NET page that couldn't be read as expected."""


def _soup(html: str | bytes) -> BeautifulSoup:
    if isinstance(html, bytes):
        html = html.decode("utf-8", "replace")
    return BeautifulSoup(html, "html.parser")


def _text(node: Tag | None) -> str:
    return node.get_text().strip() if node is not None else ""


def image_name(src: str | None) -> str | None:
    """".../img/music_icon_fc.png?ver=1.50" → "music_icon_fc"."""
    if not src:
        return None
    m = re.search(r"/([^/?]+)\.png", src)
    return m.group(1) if m else None


def _src(node: Tag | None) -> str | None:
    return node.get("src") if node is not None else None


def difficulty_code(src: str | None) -> int | None:
    names = ["diff_basic", "diff_advanced", "diff_expert", "diff_master", "diff_remaster"]
    name = image_name(src)
    return names.index(name) if name in names else None


def type_code(src: str | None) -> int | None:
    name = image_name(src)
    return 1 if name == "music_dx" else 0 if name == "music_standard" else None


def combo_code(src: str | None) -> int:
    name = image_name(src)
    return COMBO_CODES.index(COMBO_ICONS[name]) if name in COMBO_ICONS else 0


def sync_code(src: str | None) -> int:
    name = image_name(src)
    return SYNC_CODES.index(SYNC_ICONS[name]) if name in SYNC_ICONS else 0


def parse_achievement(value: str) -> int:
    """"100.5000%" → 1005000."""
    try:
        return round(float(re.sub(r"[%\s,]", "", value)) * 10000)
    except ValueError:
        return 0


def parse_dx_score(value: str) -> tuple[int, int]:
    """"1,234 / 1,500" → (1234, 1500)."""
    m = re.search(r"([\d,]+)\s*/\s*([\d,]+)", value)
    return (int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))) if m else (0, 0)


def normalize(text: str) -> str:
    """Same as the site's normalize(): NFKC, one space, lower case."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().lower()


def song_key(title: str, chart_type: int) -> str:
    return f"{normalize(title)}|{'DX' if chart_type else 'STD'}"


def _blocks(soup: BeautifulSoup) -> list[Tag]:
    return soup.select("div.main_wrapper > div")


_DIV = re.compile(r'<div\b[^>]*\bclass="([^"]*)"[^>]*>')


def _row_chunks(text: str):
    """The song rows of a record list page, one HTML piece each. These pages list every song of a
    difficulty (a few MB), and a parsed tree of a whole one takes tens of MB on a small host, so each
    row is parsed on its own (see net_parsers.parse_maimai_scores)."""
    starts = []
    for m in _DIV.finditer(text):
        classes = set(m.group(1).split())
        if "screw_block" in classes or {"w_450", "p_r", "f_0"} <= classes:
            starts.append((m.start(), "screw_block" not in classes))
    for n, (start, is_row) in enumerate(starts):
        if is_row:
            yield text[start:starts[n + 1][0] if n + 1 < len(starts) else len(text)]


def parse_chart_list(html: str | bytes) -> list[tuple[str, list]]:
    """A record/musicGenre/search page: (idx, chart) for every chart on it."""
    text = html.decode("utf-8", "replace") if isinstance(html, bytes) else html
    result = []
    for chunk in _row_chunks(text):
        block = BeautifulSoup(chunk, "html.parser").find("div")
        form = block.find("form") if block is not None else None
        idx_input = form.select_one("input[name=idx]") if form else None
        idx = idx_input.get("value") if idx_input else None
        if not form or not idx:
            continue
        difficulty = difficulty_code(_src(form.find("img")))
        title = _text(form.select_one(".music_name_block"))
        level = _text(form.select_one(".music_lv_block"))
        single = block.select_one("img.music_kind_icon")
        if single is not None:
            chart_type = type_code(single.get("src"))
        else:
            # songs with both STD and DX show two toggles; the one not being looked at has "pointer"
            std = block.select_one("img.music_kind_icon_standard")
            dx = block.select_one("img.music_kind_icon_dx")
            chart_type = 1 if std is not None and "pointer" in std.get("class", []) else                 0 if dx is not None and "pointer" in dx.get("class", []) else None
        if difficulty is None or chart_type is None or not title or level not in DISPLAY_LEVELS:
            continue
        scores = [_text(el) for el in form.select(".music_score_block")]
        score = None
        if len(scores) >= 2:
            dx_score, dx_max = parse_dx_score(scores[1])
            # float:right, so the page order is the SYNC icon, then the FC/AP icon
            icons = [img.get("src") for img in form.select("img.h_30.f_r")] + [None, None]
            score = [parse_achievement(scores[0]), dx_score, dx_max, combo_code(icons[1]), sync_code(icons[0])]
        result.append((idx, [title, chart_type, difficulty, level, None, score]))
    return result


def parse_artist(html: str | bytes) -> str | None:
    """A record/musicDetail page: the song's artist."""
    return _text(_soup(html).select_one("div.main_wrapper > div.basic_block div.m_5.f_12.break")) or None


def parse_versions(html: str | bytes) -> list[dict]:
    versions = []
    for option in _soup(html).select("select[name=version] option"):
        try:
            versions.append({"value": int(option.get("value")), "name": _text(option)})
        except (TypeError, ValueError):
            continue
    return versions


def _trophy_tier(node: Tag | None) -> str:
    classes = node.get("class", []) if node is not None else []
    for tier in ("Rainbow", "Gold", "Silver", "Bronze"):
        if f"trophy_{tier}" in classes:
            return tier
    return "Normal"


def _number_from_images(images: list[Tag], pattern: str) -> int | None:
    for img in images:
        m = re.search(pattern, image_name(img.get("src")) or "")
        if m:
            return int(m.group(1))
    return None


def _count_in(text: str, pattern: str) -> int | None:
    m = re.search(pattern, text, re.I)
    return int(m.group(1).replace(",", "")) if m else None


def parse_profile(html: str | bytes) -> dict:
    """The playerData page: name, rating, icon, title, dan/class, stars, play counts."""
    soup = _soup(html)
    block = soup.select_one("div.main_wrapper > div.see_through_block > div.basic_block")
    name = _text(block.select_one(".name_block")) if block else ""
    if block is None or not name:
        raise PageError("플레이어 정보를 읽지 못했어요.")
    trophy = block.select_one(".trophy_block")
    trophy_title = _text(trophy.select_one(".trophy_inner_block")) if trophy else ""
    images = block.find_all("img")
    stars = re.search(r"([\d,]+)", _text(block.select_one("div.p_l_10.f_l > div.p_l_10.f_l.f_14")))
    page = _text(soup.select_one("div.main_wrapper"))
    total = _count_in(page, r"total play count[：:]\s*([\d,]+)")
    current = _count_in(page, r"play count of current version[：:]\s*([\d,]+)")
    rating = _text(block.select_one(".rating_block"))
    icon = block.select_one("img.w_112")
    return {
        "name": name,
        "rating": int(rating) if rating.isdigit() else 0,
        "iconUrl": icon.get("src") if icon is not None else None,
        "trophy": {"tier": _trophy_tier(trophy), "title": trophy_title} if trophy_title else None,
        "courseRank": _number_from_images(images, r"^course_rank_(\d+)"),
        "classRank": _number_from_images(images, r"^class_rank_s?_?(\d+)"),
        "stars": int(stars.group(1).replace(",", "")) if stars else None,
        "playCount": {"total": total, "current": current or 0} if total is not None else None,
    }


def play_count(html: str | bytes) -> int | None:
    """Total play count on the playerData page (to see if there's anything new to send)."""
    return _count_in(_text(_soup(html).select_one("div.main_wrapper")), r"total play count[：:]\s*([\d,]+)")


def parse_plays(html: str | bytes) -> list[list]:
    """The record (recent plays) page."""
    plays = []
    for block in _blocks(_soup(html)):
        top = block.select_one(".playlog_top_container")
        if top is None:
            continue
        difficulty = difficulty_code(_src(top.select_one("img.playlog_diff")))
        meta = [_text(span) for span in top.select(".sub_title > span")] + ["", ""]
        track = re.search(r"TRACK\s*(\d+)", meta[0], re.I)
        date = re.search(r"(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2})", meta[1])
        title = _text(block.select_one(".basic_block"))
        chart_type = type_code(_src(block.select_one("img.playlog_music_kind_icon")))
        if difficulty is None or chart_type is None or not title or not date:
            continue
        icons = [img.get("src") for img in block.select(".playlog_result_innerblock > img")] + [None, None]
        dx_score, dx_max = parse_dx_score(_text(block.select_one(".playlog_score_block")))
        y, mo, d, h, mi = (int(x) for x in date.groups())
        # NET times are Japan time (UTC+9)
        at = datetime.datetime(y, mo, d, h, mi, tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
        plays.append([
            at.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            int(track.group(1)) if track else 0,
            title,
            chart_type,
            difficulty,
            parse_achievement(_text(block.select_one(".playlog_achievement_txt"))),
            dx_score,
            dx_max,
            combo_code(icons[0]),
            sync_code(icons[1]),
        ])
    return plays


def _stamp_progress(node: Tag) -> dict:
    count = 0
    for i in range(1, 11):
        if node.select_one(f"img.stamp_count_{i}") is not None:
            count = i
    return {
        "title": _text(node.select_one(".stampcard_inner_block")),
        "complete": node.select_one("img.stampcard_comp") is not None,
        "stampCount": count,
    }


def _stamp_type(node: Tag) -> str:
    back = _src(node.select_one("img.stampcard_back")) or ""
    for kind in ("music", "icon", "nameplate", "frame"):
        if kind in back:
            return kind
    return "other"


def parse_stamps(html: str | bytes) -> list[dict]:
    soup = _soup(html)
    cards = []
    for node in soup.select("div[name=type_partner]"):
        cards.append({"type": "partner", "imageUrl": _src(node.select_one("img.stampcard_partner")),
                      **_stamp_progress(node), "max": 10})
    for node in soup.select("div[name=type_other]"):
        kind = _stamp_type(node)
        cards.append({"type": kind, "imageUrl": _src(node.select_one(f"img.stampcard_{kind}")),
                      **_stamp_progress(node), "max": 5 if kind == "icon" else 10})
    return cards


async def collect(net, ambiguous: set[str], progress=None) -> dict:
    """Read every page the site needs with a logged-in maimai NetClient and build the upload."""
    async def page(path: str) -> bytes:
        body = await net.get(f"/maimai-mobile/{path}")
        await asyncio.sleep(REQUEST_INTERVAL)
        return body

    async def optional(path: str, parse, default):
        try:
            return parse(await page(path))
        except Exception:
            return default

    profile = parse_profile(await page("playerData/"))
    versions = await optional("record/musicVersion/", parse_versions, [])
    charts: list[tuple[str, list]] = []
    for diff in range(len(DIFFICULTY_NAMES)):
        if progress:
            await progress(f"곡 목록 읽는 중... {DIFFICULTY_NAMES[diff]} ({diff + 1}/5)")
        body = await page(f"record/musicGenre/search/?genre=99&diff={diff}")
        charts += await asyncio.to_thread(parse_chart_list, body)
        del body
    if not charts:
        raise PageError("곡 목록을 읽지 못했어요.")

    # songs that share a title (and type) are told apart by artist, from their detail page
    counts: dict[str, int] = {}
    for _, chart in charts:
        key = f"{song_key(chart[0], chart[1])}|{chart[2]}"
        counts[key] = counts.get(key, 0) + 1
    artists: dict[str, str | None] = {}
    for idx, chart in charts:
        key = song_key(chart[0], chart[1])
        if key in ambiguous or counts[f"{key}|{chart[2]}"] > 1:
            if idx not in artists:
                artists[idx] = await optional(f"record/musicDetail/?idx={quote(idx, safe='')}", parse_artist, None)
            chart[4] = artists[idx]

    plays = await optional("record/", parse_plays, [])
    stamps = await optional("playerData/stampCard/", parse_stamps, [])
    return {
        "v": PAYLOAD_VERSION,
        "profile": profile,
        "charts": [chart for _, chart in charts],
        "plays": plays,
        "stamps": stamps,
        "versions": versions,
    }
