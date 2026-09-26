"""Render a B50 as a PNG image."""

from __future__ import annotations

import io
import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .b50 import B50, SLOTS, Entry

COLS = 5
CARD_W, CARD_H = 272, 112
GAP = 10
MARGIN = 24
HEADER_H = 150
SECTION_H = 46

BG = (24, 26, 33)
CARD_BG = (38, 41, 52)
TEXT = (235, 237, 243)
SUBTEXT = (160, 166, 182)

DIFF_COLORS = {
    "basic": (69, 193, 36),
    "advanced": (255, 170, 0),
    "expert": (255, 90, 102),
    "master": (159, 81, 220),
    "re:master": (219, 170, 255),
    "ultima": (230, 40, 60),
    "world's end": (90, 200, 220),
}

DIFF_SHORT = {
    "basic": "BAS",
    "advanced": "ADV",
    "expert": "EXP",
    "master": "MAS",
    "re:master": "Re:MAS",
    "ultima": "ULT",
    "world's end": "WE",
}

RANK_COLORS = {
    "SSS+": (255, 215, 90),
    "SSS": (255, 200, 80),
    "SS+": (240, 180, 70),
    "SS": (230, 170, 70),
    "S+": (210, 160, 80),
    "S": (200, 150, 80),
}

GAME_TITLES = {"maimai": "maimai DX", "chunithm": "CHUNITHM"}

# Fonts covering both Japanese (song titles) and Korean (labels).
FONT_CANDIDATES = [
    str(Path(__file__).parent / "assets" / "fonts"),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
]
# Otherwise fall back to one system font per script (e.g. on Windows, where
# Malgun Gothic lacks many kanji and Yu Gothic/Meiryo lack Hangul).
JA_FONTS = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
]
KO_FONTS = [
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/malgun.ttf",
]


def _first_existing(candidates: list[str]) -> str | None:
    for c in candidates:
        if not c:
            continue
        p = Path(c)
        if p.is_dir():
            files = sorted(f for f in p.iterdir() if f.suffix.lower() in {".ttf", ".otf", ".ttc"})
            if files:
                return str(files[0])
        elif p.is_file():
            return str(p)
    return None


def _find_font_file(script: str) -> str | None:
    both = _first_existing([os.environ.get("FONT_PATH", ""), *FONT_CANDIDATES])
    if both:
        return both
    primary, secondary = (JA_FONTS, KO_FONTS) if script == "ja" else (KO_FONTS, JA_FONTS)
    return _first_existing(primary) or _first_existing(secondary)


@lru_cache(maxsize=None)
def font(size: int, script: str = "ja") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """`script="ja"` for song titles / player names, `"ko"` for Korean labels."""
    path = _find_font_file(script)
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _fit(draw: ImageDraw.ImageDraw, text: str, f, max_w: int) -> str:
    if draw.textlength(text, font=f) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=f) > max_w:
        text = text[:-1]
    return text + "…"


def _diff_key(difficulty: str) -> str:
    d = difficulty.lower()
    return d[3:] if d.startswith("dx ") else d


def _draw_card(img: Image.Image, draw: ImageDraw.ImageDraw, x: int, y: int, idx: int, e: Entry) -> None:
    key = _diff_key(e.difficulty)
    color = DIFF_COLORS.get(key, (120, 120, 120))
    draw.rounded_rectangle((x, y, x + CARD_W, y + CARD_H), radius=10, fill=CARD_BG)
    draw.rounded_rectangle((x, y, x + 8, y + CARD_H), radius=4, fill=color)

    px = x + 18
    draw.text((px, y + 8), _fit(draw, e.title, font(17), CARD_W - 30), font=font(17), fill=TEXT)

    dx = " DX" if e.difficulty.lower().startswith("dx ") else ""
    const = f"{e.level_const:.1f}" if e.level_const else "?"
    diff_label = f"{DIFF_SHORT.get(key, e.difficulty)}{dx} {e.level} ({const})"
    draw.text((px, y + 34), diff_label, font=font(14), fill=color)
    draw.text((x + CARD_W - 12, y + 34), f"#{idx}", font=font(14), fill=SUBTEXT, anchor="ra")

    draw.text((px, y + 58), e.score_text, font=font(18), fill=TEXT)
    rank_text = e.rank + (f"  {e.lamp}" if e.lamp else "")
    draw.text((px, y + 84), rank_text, font=font(15), fill=RANK_COLORS.get(e.rank, SUBTEXT))

    draw.text((x + CARD_W - 12, y + CARD_H - 10), e.rating_text, font=font(26), fill=TEXT, anchor="rd")


def _draw_section(img, draw, y: int, title: str, entries: list[Entry], slots: int) -> int:
    draw.text((MARGIN, y + 12), title, font=font(22, "ko"), fill=TEXT)
    y += SECTION_H
    rows = max(1, -(-slots // COLS))
    for i, e in enumerate(entries):
        r, c = divmod(i, COLS)
        _draw_card(img, draw, MARGIN + c * (CARD_W + GAP), y + r * (CARD_H + GAP), i + 1, e)
    return y + rows * (CARD_H + GAP)


def render_b50(b50: B50) -> bytes:
    old_slots, new_slots = SLOTS[b50.game]
    rows = -(-old_slots // COLS) + -(-new_slots // COLS)
    width = MARGIN * 2 + COLS * CARD_W + (COLS - 1) * GAP
    height = HEADER_H + 2 * SECTION_H + rows * (CARD_H + GAP) + MARGIN

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    draw.text((MARGIN, 22), f"{GAME_TITLES[b50.game]}  BEST 50", font=font(22), fill=SUBTEXT)
    draw.text((MARGIN, 52), b50.username, font=font(40), fill=TEXT)
    draw.text((width - MARGIN, 30), "RATING", font=font(20), fill=SUBTEXT, anchor="ra")
    shown = b50.official_rating or b50.total_text()
    draw.text((width - MARGIN, 56), shown, font=font(56), fill=(255, 215, 90), anchor="ra")
    if b50.official_rating and b50.official_rating != b50.total_text():
        draw.text((width - MARGIN, 124), f"계산값 {b50.total_text()}", font=font(15, "ko"), fill=SUBTEXT, anchor="ra")

    fmt = (lambda v: f"{float(v):.2f}") if b50.game == "chunithm" else (lambda v: str(int(v)))
    summary = (
        f"구곡 합계 {fmt(b50.old_sum)} (평균 {b50.average_text(b50.old)})    "
        f"신곡 합계 {fmt(b50.new_sum)} (평균 {b50.average_text(b50.new)})"
    )
    draw.text((MARGIN, 112), summary, font=font(17, "ko"), fill=SUBTEXT)

    y = HEADER_H
    y = _draw_section(img, draw, y, f"BEST {old_slots}  ·  구곡", b50.old, old_slots)
    _draw_section(img, draw, y, f"BEST {new_slots}  ·  신곡", b50.new, new_slots)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
