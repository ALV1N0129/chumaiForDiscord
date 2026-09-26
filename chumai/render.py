"""Render a B50 as a PNG image."""

from __future__ import annotations

import io
import os
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .b50 import B50, SLOTS, Entry

ASSETS = Path(__file__).parent / "assets"

COLS = 5
CARD_W, CARD_H = 372, 132
GAP_X, GAP_Y = 14, 14
MARGIN = 40
HEADER_H = 236
SECTION_H = 64
FOOTER_H = 56
JACKET = 108
RADIUS = 14

WHITE = (255, 255, 255)
MUTED = (178, 184, 204)
FAINT = (120, 126, 148)

THEMES = {
    "maimai": {"top": (58, 30, 74), "bottom": (16, 18, 36), "accent": (255, 132, 186), "card": (40, 36, 60)},
    "chunithm": {"top": (18, 44, 84), "bottom": (8, 12, 26), "accent": (255, 214, 64), "card": (28, 36, 58)},
}

DIFFS = {
    "basic": ("BAS", (46, 180, 80)),
    "advanced": ("ADV", (242, 152, 0)),
    "expert": ("EXP", (232, 62, 86)),
    "master": ("MAS", (146, 72, 222)),
    "re:master": ("Re:M", (200, 150, 255)),
    "ultima": ("ULT", (170, 24, 56)),
    "world's end": ("WE", (40, 170, 190)),
}

RANK_COLORS = {
    "SSS+": (255, 214, 80),
    "SSS": (255, 214, 80),
    "SS+": (255, 190, 90),
    "SS": (255, 190, 90),
    "S+": (240, 170, 110),
    "S": (240, 170, 110),
}

LAMP_COLORS = {
    "AP+": (255, 190, 40),
    "AP": (255, 190, 40),
    "AJC": (255, 190, 40),
    "AJ": (255, 190, 40),
    "FC+": (70, 205, 120),
    "FC": (70, 205, 120),
}

# In-game rating plate colors: (threshold, color or list of colors for a gradient)
RAINBOW = [(255, 96, 96), (255, 190, 70), (120, 220, 110), (80, 170, 255), (190, 110, 255)]
PLATES = {
    "maimai": [
        (15000, RAINBOW),
        (14500, [(222, 230, 240), (170, 190, 215)]),
        (14000, [(255, 216, 90), (214, 160, 40)]),
        (13000, [(214, 220, 232), (150, 160, 180)]),
        (12000, [(214, 140, 90), (160, 90, 50)]),
        (10000, [(170, 100, 230), (120, 60, 190)]),
        (7000, [(240, 90, 90), (190, 50, 60)]),
        (4000, [(250, 200, 60), (210, 160, 30)]),
        (2000, [(90, 200, 110), (50, 150, 80)]),
        (1000, [(80, 160, 250), (50, 110, 210)]),
        (0, [(200, 204, 214), (150, 154, 166)]),
    ],
    "chunithm": [
        (16.0, RAINBOW),
        (15.25, [(222, 230, 240), (170, 190, 215)]),
        (14.5, [(255, 216, 90), (214, 160, 40)]),
        (13.25, [(214, 220, 232), (150, 160, 180)]),
        (12.0, [(214, 140, 90), (160, 90, 50)]),
        (10.0, [(170, 100, 230), (120, 60, 190)]),
        (7.0, [(240, 90, 90), (190, 50, 60)]),
        (4.0, [(250, 150, 50), (210, 110, 30)]),
        (0, [(90, 200, 110), (50, 150, 80)]),
    ],
}

GAME_NAMES = {"maimai": "maimai DX", "chunithm": "CHUNITHM"}

# ------------------------------------------------------------------ fonts

CJK_BOLD = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
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


def _cjk_font_file() -> str | None:
    return _first_existing([os.environ.get("FONT_PATH", ""), str(ASSETS / "fonts"), *CJK_BOLD])


@lru_cache(maxsize=None)
def cjk(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Song titles and player names (Japanese/full-width text)."""
    path = _cjk_font_file()
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


@lru_cache(maxsize=None)
def num(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    """Numbers and short Latin labels."""
    return ImageFont.truetype(str(ASSETS / "display" / f"BarlowCondensed-{weight}.ttf"), size)


# ---------------------------------------------------------------- helpers


def _fit(draw: ImageDraw.ImageDraw, text: str, f, max_w: int) -> str:
    if draw.textlength(text, font=f) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=f) > max_w:
        text = text[:-1]
    return text + "…"


def _vertical_gradient(size: tuple[int, int], top, bottom) -> Image.Image:
    w, h = size
    col = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        col.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return col.resize((w, h))


def _horizontal_gradient(size: tuple[int, int], stops) -> Image.Image:
    w, h = size
    row = Image.new("RGB", (w, 1))
    n = len(stops) - 1
    for x in range(w):
        t = x / max(1, w - 1) * n
        i = min(int(t), n - 1)
        f = t - i
        a, b = stops[i], stops[i + 1]
        row.putpixel((x, 0), tuple(round(a[k] + (b[k] - a[k]) * f) for k in range(3)))
    return row.resize((w, h))


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _diff(e: Entry) -> tuple[str, tuple[int, int, int], bool]:
    d = e.difficulty.lower()
    is_dx = d.startswith("dx ")
    label, color = DIFFS.get(d[3:] if is_dx else d, (e.difficulty[:4].upper(), (110, 110, 110)))
    return label, color, is_dx


@lru_cache(maxsize=256)
def _load_jacket(path: str) -> Image.Image | None:
    try:
        with Image.open(path) as im:
            return ImageOps.fit(im.convert("RGB"), (JACKET, JACKET), Image.LANCZOS)
    except Exception:
        return None


@lru_cache(maxsize=256)
def _card_background(path: str | None, fallback: tuple[int, int, int]) -> Image.Image:
    if path:
        try:
            with Image.open(path) as im:
                bg = ImageOps.fit(im.convert("RGB"), (CARD_W, CARD_H), Image.LANCZOS, centering=(0.5, 0.4))
            bg = bg.filter(ImageFilter.GaussianBlur(14))
            return Image.blend(bg, Image.new("RGB", bg.size, (10, 10, 18)), 0.62)
        except Exception:
            pass
    return Image.new("RGB", (CARD_W, CARD_H), fallback)


# ------------------------------------------------------------------- card


def _draw_card(canvas: Image.Image, x: int, y: int, idx: int, e: Entry, theme: dict) -> None:
    label, color, is_dx = _diff(e)

    canvas.paste(_card_background(e.jacket_path, theme["card"]), (x, y), _rounded_mask((CARD_W, CARD_H), RADIUS))
    draw = ImageDraw.Draw(canvas)

    # jacket with a difficulty-colored frame and a level tag along the bottom
    jx, jy = x + 12, y + 12
    draw.rounded_rectangle((jx - 3, jy - 3, jx + JACKET + 2, jy + JACKET + 2), radius=9, fill=color)
    jacket = _load_jacket(e.jacket_path) if e.jacket_path else None
    if jacket is None:
        jacket = Image.new("RGB", (JACKET, JACKET), (24, 24, 32))
        ImageDraw.Draw(jacket).text((JACKET // 2, JACKET // 2 - 8), "NO IMAGE", font=num(16, "SemiBold"),
                                    fill=FAINT, anchor="mm")
    canvas.paste(jacket, (jx, jy), _rounded_mask((JACKET, JACKET), 7))
    tag_h = 24
    draw.rectangle((jx, jy + JACKET - tag_h, jx + JACKET - 1, jy + JACKET - 1), fill=color)
    const = f"{e.level_const:.1f}" if e.level_const else e.level
    # light tags (Re:MASTER) need dark text
    tag_text = (60, 24, 96) if sum(color) > 560 else WHITE
    draw.text((jx + 6, jy + JACKET - tag_h / 2), label, font=num(17), fill=tag_text, anchor="lm")
    draw.text((jx + JACKET - 6, jy + JACKET - tag_h / 2), const, font=num(17), fill=tag_text, anchor="rm")
    if is_dx:
        draw.rounded_rectangle((jx + 4, jy + 4, jx + 30, jy + 20), radius=4, fill=(255, 255, 255))
        draw.text((jx + 17, jy + 12), "DX", font=num(14), fill=(230, 70, 110), anchor="mm")

    # text column
    tx = jx + JACKET + 16
    right = x + CARD_W - 14
    draw.text((right, y + 12), f"#{idx}", font=num(17, "SemiBold"), fill=FAINT, anchor="ra")
    title_w = right - tx - 30
    draw.text((tx, y + 10), _fit(draw, e.title, cjk(17), title_w), font=cjk(17), fill=WHITE)

    score = f"{e.score:.4f}%" if e.game == "maimai" else f"{int(e.score):,}"
    draw.text((tx, y + 38), score, font=num(32), fill=WHITE)

    rx = tx
    rank_font = num(20)
    draw.text((rx, y + 86), e.rank, font=rank_font, fill=RANK_COLORS.get(e.rank, MUTED))
    rx += draw.textlength(e.rank, font=rank_font) + 8
    if e.lamp:
        lf = num(15)
        w = draw.textlength(e.lamp, font=lf) + 12
        lamp_color = LAMP_COLORS.get(e.lamp, MUTED)
        draw.rounded_rectangle((rx, y + 89, rx + w, y + 109), radius=5, outline=lamp_color, width=2)
        draw.text((rx + w / 2, y + 99), e.lamp, font=lf, fill=lamp_color, anchor="mm")

    draw.text((right, y + CARD_H - 10), e.rating_text, font=num(34), fill=WHITE, anchor="rd")


# ----------------------------------------------------------------- header


def _plate_colors(game: str, value: str) -> list[tuple[int, int, int]]:
    try:
        v = float(value)
    except ValueError:
        return PLATES[game][-1][1]
    for threshold, colors in PLATES[game]:
        if v >= threshold:
            return colors
    return PLATES[game][-1][1]


def _stat(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, value: str) -> int:
    draw.text((x, y), label, font=num(16, "SemiBold"), fill=FAINT)
    draw.text((x, y + 20), value, font=num(30), fill=WHITE)
    return int(x + max(draw.textlength(label, font=num(16, "SemiBold")), draw.textlength(value, font=num(30)))) + 36


def _draw_header(canvas: Image.Image, b50: B50, width: int, theme: dict) -> None:
    draw = ImageDraw.Draw(canvas)
    old_slots, new_slots = SLOTS[b50.game]

    draw.text((MARGIN, 38), f"{GAME_NAMES[b50.game].upper()}   BEST {old_slots + new_slots}",
              font=num(20, "SemiBold"), fill=theme["accent"])
    # Official sites use full-width letters for names (ＡＬＶ１Ｎ); show them normally.
    name = unicodedata.normalize("NFKC", b50.username)
    draw.text((MARGIN - 2, 62), _fit(draw, name, cjk(52), width - 520), font=cjk(52), fill=WHITE)

    fmt = (lambda v: f"{float(v):.2f}") if b50.game == "chunithm" else (lambda v: str(int(v)))
    x = MARGIN
    x = _stat(draw, x, 150, f"BEST {old_slots} TOTAL", fmt(b50.old_sum))
    x = _stat(draw, x, 150, f"NEW {new_slots} TOTAL", fmt(b50.new_sum))
    x = _stat(draw, x, 150, f"BEST {old_slots} AVG", b50.average_text(b50.old))
    x = _stat(draw, x, 150, f"NEW {new_slots} AVG", b50.average_text(b50.new))

    # rating plate
    rating = b50.official_rating or b50.total_text()
    pw, ph = 330, 128
    px, py = width - MARGIN - pw, 44
    colors = _plate_colors(b50.game, rating)
    plate = _horizontal_gradient((pw, ph), colors if len(colors) > 1 else colors * 2)
    canvas.paste(plate, (px, py), _rounded_mask((pw, ph), 18))
    draw.text((px + 22, py + 14), "RATING", font=num(20, "SemiBold"), fill=(20, 20, 30))
    draw.text((px + pw - 22, py + ph - 10), rating, font=num(76), fill=(255, 255, 255), anchor="rd",
              stroke_width=3, stroke_fill=(20, 20, 30))
    if b50.official_rating and b50.official_rating != b50.total_text():
        draw.text((px + pw, py + ph + 10), f"CALCULATED {b50.total_text()}", font=num(16, "SemiBold"),
                  fill=FAINT, anchor="ra")


def _draw_section(canvas: Image.Image, y: int, title: str, sub: str, width: int, theme: dict) -> int:
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((MARGIN, y + 22, MARGIN + 5, y + 46), fill=theme["accent"])
    draw.text((MARGIN + 16, y + 34), title, font=num(28), fill=WHITE, anchor="lm")
    tw = draw.textlength(title, font=num(28))
    draw.text((MARGIN + 28 + tw, y + 36), sub, font=num(18, "SemiBold"), fill=FAINT, anchor="lm")
    line_x = MARGIN + 44 + tw + draw.textlength(sub, font=num(18, "SemiBold"))
    draw.line((line_x, y + 35, width - MARGIN, y + 35), fill=(255, 255, 255, 40), width=1)
    return y + SECTION_H


def render_b50(b50: B50, now: datetime | None = None) -> bytes:
    theme = THEMES[b50.game]
    old_slots, new_slots = SLOTS[b50.game]
    old_rows, new_rows = -(-old_slots // COLS), -(-new_slots // COLS)
    width = MARGIN * 2 + COLS * CARD_W + (COLS - 1) * GAP_X
    height = (HEADER_H + 2 * SECTION_H + (old_rows + new_rows) * (CARD_H + GAP_Y) + FOOTER_H)

    canvas = _vertical_gradient((width, height), theme["top"], theme["bottom"]).convert("RGBA")
    _draw_header(canvas, b50, width, theme)

    y = HEADER_H
    for title, sub, entries, rows in (
        (f"BEST {old_slots}", "OLD VERSIONS", b50.old, old_rows),
        (f"NEW {new_slots}", "CURRENT VERSION", b50.new, new_rows),
    ):
        y = _draw_section(canvas, y, title, sub, width, theme)
        for i, e in enumerate(entries):
            r, c = divmod(i, COLS)
            _draw_card(canvas, MARGIN + c * (CARD_W + GAP_X), y + r * (CARD_H + GAP_Y), i + 1, e, theme)
        y += rows * (CARD_H + GAP_Y)

    draw = ImageDraw.Draw(canvas)
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    source = f"{b50.source}  ·  " if b50.source else ""
    draw.text((width - MARGIN, height - 28), f"{source}{stamp}", font=num(17, "Medium"), fill=FAINT, anchor="rm")

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
