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
HEADER_H = 250
SECTION_H = 64
FOOTER_H = 56
JACKET = 108
RADIUS = 14

WHITE = (255, 255, 255)
MAX_RATING = (255, 222, 110)  # rating number when the chart's max rating is reached
MUTED = (178, 184, 204)
FAINT = (120, 126, 148)

THEMES = {
    "maimai": {"top": (58, 30, 74), "bottom": (16, 18, 36), "accent": (255, 132, 186), "glow2": (90, 170, 255),
               "card": (34, 30, 52)},
    "chunithm": {"top": (18, 44, 84), "bottom": (8, 12, 26), "accent": (255, 214, 64), "glow2": (60, 200, 255),
                 "card": (22, 30, 50)},
}

# Look of the page. "text"/"muted"/"faint" are text colors on cards and header.
STYLES = {
    "glow": {"bg": "glow", "card": "jacket", "text": (255, 255, 255), "muted": (178, 184, 204),
             "faint": (130, 136, 160), "rank": (255, 206, 84)},
    "collage": {"bg": "collage", "card": "jacket", "text": (255, 255, 255), "muted": (190, 194, 210),
                "faint": (150, 154, 172), "rank": (255, 206, 84)},
    "clean": {"bg": "glow", "card": "jacket", "text": (255, 255, 255), "muted": (178, 184, 204),
              "faint": (130, 136, 160), "rank": (255, 206, 84)},
    "calm": {"bg": "collage_dim", "card": "jacket", "text": (255, 255, 255), "muted": (190, 194, 210),
             "faint": (150, 154, 172), "rank": (255, 206, 84)},
    "light": {"bg": "light", "card": "light", "text": (28, 28, 40), "muted": (92, 96, 116),
              "faint": (140, 144, 162), "rank": (214, 146, 0)},
}
DEFAULT_STYLE = "collage"

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
        (16000, RAINBOW),
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
        (17.0, RAINBOW),
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
def _card_background(path: str | None, mode: str, fallback: tuple[int, int, int]) -> Image.Image:
    """RGBA card background. The jacket shows through on the right, fading out to the left."""
    if mode == "light":
        return Image.new("RGBA", (CARD_W, CARD_H), (255, 255, 255, 236))
    base = Image.new("RGBA", (CARD_W, CARD_H), (*fallback, 228))
    if mode == "flat":
        return Image.new("RGBA", (CARD_W, CARD_H), (*fallback, 235))
    if not path:
        return base
    try:
        with Image.open(path) as im:
            art = ImageOps.fit(im.convert("RGB"), (CARD_W, CARD_W), Image.LANCZOS)
    except Exception:
        return base
    art = art.crop((0, (CARD_W - CARD_H) // 2, CARD_W, (CARD_W + CARD_H) // 2))
    art = Image.blend(art, Image.new("RGB", art.size, (12, 12, 20)), 0.35).convert("RGBA")
    fade = Image.linear_gradient("L").rotate(90).resize((CARD_W, CARD_H))  # 255 at left -> 0 at right
    fade = fade.point(lambda v: 255 - v)  # 0 at left -> 255 at right
    fade = fade.point(lambda v: int(min(255, max(0, (v - 40) * 1.3))))
    art.putalpha(fade)
    return Image.alpha_composite(base, art)


# ------------------------------------------------------------------- card


def _draw_card(canvas: Image.Image, x: int, y: int, idx: int, e: Entry, theme: dict, st: dict) -> None:
    label, color, is_dx = _diff(e)
    mask = _rounded_mask((CARD_W, CARD_H), RADIUS)
    if st["card"] == "light":
        shadow = Image.new("RGBA", (CARD_W + 24, CARD_H + 24), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((12, 16, CARD_W + 11, CARD_H + 15), radius=RADIUS,
                                                 fill=(60, 40, 90, 40))
        shadow = shadow.filter(ImageFilter.GaussianBlur(7))
        canvas.alpha_composite(shadow, (x - 12, y - 12))
    bg = _card_background(e.jacket_path, st["card"], theme["card"])
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    card.paste(bg, (0, 0), mask)
    canvas.alpha_composite(card, (x, y))
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
    draw.text((right, y + 12), f"#{idx}", font=num(17, "SemiBold"), fill=st["faint"], anchor="ra")
    title_w = right - tx - 30
    draw.text((tx, y + 10), _fit(draw, e.title, cjk(17), title_w), font=cjk(17), fill=st["text"])

    score = f"{e.score:.4f}%" if e.game == "maimai" else f"{int(e.score):,}"
    draw.text((tx, y + 38), score, font=num(32), fill=st["text"])

    rx = tx
    rank_font = num(20)
    top_rank = e.rank in RANK_COLORS
    draw.text((rx, y + 86), e.rank, font=rank_font, fill=st["rank"] if top_rank else st["muted"])
    rx += draw.textlength(e.rank, font=rank_font) + 8
    if e.lamp:
        lf = num(15)
        w = draw.textlength(e.lamp, font=lf) + 12
        lamp_color = LAMP_COLORS.get(e.lamp, st["muted"])
        draw.rounded_rectangle((rx, y + 89, rx + w, y + 109), radius=5, outline=lamp_color, width=2)
        draw.text((rx + w / 2, y + 99), e.lamp, font=lf, fill=lamp_color, anchor="mm")

    maxed = e.score >= (100.5 if e.game == "maimai" else 1_009_000)
    draw.text((right, y + CARD_H - 10), e.rating_text, font=num(34),
              fill=MAX_RATING if maxed else st["text"], anchor="rd")


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


def _stat(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, value: str, st: dict) -> int:
    draw.text((x, y), label, font=num(16, "SemiBold"), fill=st["faint"])
    draw.text((x, y + 20), value, font=num(30), fill=st["text"])
    return int(x + max(draw.textlength(label, font=num(16, "SemiBold")), draw.textlength(value, font=num(30)))) + 36


LOGO_BOX = (520, 216)  # logo area, centered at the top
LOGO_GRADIENTS = {
    "maimai": [(255, 120, 190), (255, 196, 90), (110, 214, 255)],
    "chunithm": [(255, 226, 90), (255, 150, 60), (240, 70, 120)],
}


def _gradient_text(text: str, font, stops) -> Image.Image:
    """Text filled with a horizontal gradient, with a soft shadow."""
    l, t, r, b = font.getbbox(text)
    w, h = r - l + 16, b - t + 16
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((8 - l, 8 - t), text, font=font, fill=255)
    fill = _horizontal_gradient((w, h), stops).convert("RGBA")
    fill.putalpha(mask)
    out = Image.new("RGBA", (w, h + 6), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow.putalpha(mask.point(lambda v: v * 110 // 255))
    out.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(4)), (0, 5))
    out.alpha_composite(fill, (0, 0))
    return out


# Where downloaded official logos live (see logos.py); the bot sets this from config.
LOGO_DIR = Path(os.environ.get("LOGO_DIR", "data/logos"))


def _logo_image(game: str) -> Image.Image:
    """Official logo (downloaded via .env URL, else bundled in assets/logos/), or a text wordmark."""
    for path in (LOGO_DIR / f"{game}.png", ASSETS / "logos" / f"{game}.png"):
        if not path.is_file():
            continue
        try:
            with Image.open(path) as im:
                logo = im.convert("RGBA")
            bbox = logo.getbbox()  # trim transparent margins
            if bbox:
                logo = logo.crop(bbox)
            scale = min(LOGO_BOX[0] / logo.width, LOGO_BOX[1] / logo.height)  # may enlarge
            return logo.resize((round(logo.width * scale), round(logo.height * scale)), Image.LANCZOS)
        except Exception:
            continue
    stops = LOGO_GRADIENTS[game]
    if game == "maimai":
        word = _gradient_text("maimai", num(104), stops)
        dx = Image.new("RGBA", (96, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(dx)
        d.rounded_rectangle((0, 0, 95, 63), radius=14, fill=(255, 255, 255))
        d.text((48, 32), "DX", font=num(50), fill=(236, 70, 120), anchor="mm")
        logo = Image.new("RGBA", (word.width + 110, max(word.height, 100)), (0, 0, 0, 0))
        logo.alpha_composite(word, (0, (logo.height - word.height) // 2))
        logo.alpha_composite(dx, (word.width + 10, (logo.height - 64) // 2 + 6))
    else:
        logo = _gradient_text("CHUNITHM", num(96), stops)
    logo.thumbnail(LOGO_BOX, Image.LANCZOS)
    return logo


def _draw_logo(canvas: Image.Image, game: str, width: int, theme: dict) -> None:
    logo = _logo_image(game)
    canvas.alpha_composite(logo, ((width - logo.width) // 2, 10 + (LOGO_BOX[1] - logo.height) // 2))


TITLE_COLORS = {
    "normal": [(232, 232, 236)],
    "copper": [(214, 140, 90)],
    "bronze": [(214, 140, 90)],
    "silver": [(200, 208, 222)],
    "gold": [(250, 206, 70)],
    "platina": [(226, 238, 250), (190, 210, 235)],
    "platinum": [(226, 238, 250), (190, 210, 235)],
    "rainbow": RAINBOW,
    "staff": RAINBOW,
}


def _open_image(data: bytes | None) -> Image.Image | None:
    if not data:
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.convert("RGBA")
    except Exception:
        return None


def _title_badge(text: str, rarity: str | None, max_w: int) -> Image.Image:
    colors = TITLE_COLORS.get((rarity or "normal").lower(), TITLE_COLORS["normal"])
    f = cjk(15)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    text = _fit(probe, text, f, max_w - 24)
    w, h = int(probe.textlength(text, font=f)) + 24, 26
    badge = _gradient_fill((w, h), colors)
    badge.putalpha(_rounded_mask((w, h), 13))
    ImageDraw.Draw(badge).text((w // 2, h // 2), text, font=f, fill=(24, 22, 34), anchor="mm")
    return badge


def _draw_player_card(canvas: Image.Image, b50: B50, theme: dict, st: dict) -> None:
    """Simple plate: the player's icon and name."""
    old_slots, new_slots = SLOTS[b50.game]
    cw, ch = 560, 136  # same height as the rating plate
    cx, cy = MARGIN, 40

    card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    body = Image.new("RGBA", (cw, ch), (*theme["card"], 235))
    body.paste(_gradient_fill((6, ch), [theme["accent"], theme["glow2"]]), (0, 0))
    card.paste(body, (0, 0), _rounded_mask((cw, ch), 18))
    ImageDraw.Draw(card).rounded_rectangle((0, 0, cw - 1, ch - 1), radius=18, outline=(255, 255, 255, 40), width=2)
    canvas.alpha_composite(card, (cx, cy))
    draw = ImageDraw.Draw(canvas)

    tx = cx + 30
    icon = _open_image(b50.icon)
    if icon is not None:
        size = ch - 28
        icon = ImageOps.fit(icon, (size, size), Image.LANCZOS)
        ix, iy = cx + 20, cy + 14
        framed = Image.new("RGBA", (size, size), (20, 18, 30, 255))
        framed.alpha_composite(icon)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(framed, (0, 0), _rounded_mask((size, size), 14))
        canvas.alpha_composite(out, (ix, iy))
        draw.rounded_rectangle((ix - 1, iy - 1, ix + size, iy + size), radius=15, outline=(255, 255, 255, 90), width=2)
        tx = ix + size + 24

    name = unicodedata.normalize("NFKC", b50.username)  # official sites use full-width letters
    draw.text((tx, cy + 34), f"{GAME_NAMES[b50.game].upper()}  PLAYER", font=num(18, "SemiBold"),
              fill=theme["accent"], anchor="ls")
    draw.text((tx - 2, cy + 94), _fit(draw, name, cjk(46), cx + cw - 20 - tx), font=cjk(46), fill=st["text"],
              anchor="ls")

    # stats as a row of chips under the card
    fmt = (lambda v: f"{float(v):.2f}") if b50.game == "chunithm" else (lambda v: str(int(v)))
    stats = [
        (f"BEST {old_slots}", fmt(b50.old_sum)),
        (f"NEW {new_slots}", fmt(b50.new_sum)),
        (f"B{old_slots} AVG", b50.average_text(b50.old)),
        (f"N{new_slots} AVG", b50.average_text(b50.new)),
    ]
    sx, sy = cx, cy + ch + 10
    for label, value in stats:
        lw = draw.textlength(label, font=num(15, "SemiBold"))
        vw = draw.textlength(value, font=num(22))
        w = int(lw + vw + 30)
        chip = Image.new("RGBA", (w, 34), (0, 0, 0, 0))
        chip.paste(Image.new("RGBA", (w, 34), (10, 8, 18, 150)), (0, 0), _rounded_mask((w, 34), 17))
        canvas.alpha_composite(chip, (sx, sy))
        draw.text((sx + 12, sy + 17), label, font=num(15, "SemiBold"), fill=st["faint"], anchor="lm")
        draw.text((sx + w - 12, sy + 18), value, font=num(22), fill=st["text"], anchor="rm")
        sx += w + 8


def _draw_header(canvas: Image.Image, b50: B50, width: int, theme: dict, st: dict) -> None:
    draw = ImageDraw.Draw(canvas)
    old_slots, new_slots = SLOTS[b50.game]

    _draw_logo(canvas, b50.game, width, theme)
    _draw_player_card(canvas, b50, theme, st)

    rating = b50.official_rating or b50.total_text()
    _draw_plate(canvas, b50.game, rating, width, st)
    if b50.official_rating and b50.official_rating != b50.total_text():
        draw.text((width - MARGIN, 190), f"CALCULATED {b50.total_text()}", font=num(16, "SemiBold"),
                  fill=st["faint"], anchor="ra")


TIER_NAMES = {
    "maimai": ["極 RAINBOW", "RAINBOW", "PLATINUM", "GOLD", "SILVER", "BRONZE", "PURPLE", "RED", "YELLOW", "GREEN", "BLUE", "WHITE"],
    "chunithm": ["極 RAINBOW", "RAINBOW", "PLATINUM", "GOLD", "SILVER", "BRONZE", "PURPLE", "RED", "ORANGE", "GREEN"],
}
PLATE_STYLE = os.environ.get("PLATE_STYLE", "glass")


def _tier_name(game: str, value: str) -> str:
    try:
        v = float(value)
    except ValueError:
        return ""
    for (threshold, _), name in zip(PLATES[game], TIER_NAMES[game]):
        if v >= threshold:
            return name
    return TIER_NAMES[game][-1]


def _gradient_fill(size: tuple[int, int], colors) -> Image.Image:
    return _horizontal_gradient(size, colors if len(colors) > 1 else colors * 2).convert("RGBA")


def _draw_plate(canvas: Image.Image, game: str, rating: str, width: int, st: dict) -> None:
    colors = _plate_colors(game, rating)
    tier = _tier_name(game, rating)
    draw = ImageDraw.Draw(canvas)
    right = width - MARGIN

    if PLATE_STYLE == "glass":
        # dark translucent panel, tier-colored outline, gradient number
        pw, ph = 340, 136
        px, py = right - pw, 40
        if tier.startswith("極"):
            glow = _gradient_fill((pw + 40, ph + 40), colors)
            gm = Image.new("L", glow.size, 0)
            ImageDraw.Draw(gm).rounded_rectangle((20, 20, pw + 19, ph + 19), radius=20, fill=200)
            glow.putalpha(gm.filter(ImageFilter.GaussianBlur(12)))
            canvas.alpha_composite(glow, (px - 20, py - 20))
        panel = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        border = _gradient_fill((pw, ph), colors)
        border.putalpha(_rounded_mask((pw, ph), 20))
        panel.alpha_composite(border)
        inner = Image.new("RGBA", (pw - 6, ph - 6), (14, 12, 24, 225))
        inner.putalpha(_rounded_mask((pw - 6, ph - 6), 17).point(lambda v: v * 225 // 255))
        panel.alpha_composite(inner, (3, 3))
        canvas.alpha_composite(panel, (px, py))
        draw.text((px + 22, py + 18), "RATING", font=num(18, "SemiBold"), fill=st["muted"])
        if tier.startswith("極"):
            label = _gradient_text("極 RAINBOW", cjk(18), [tuple(min(255, c + 40) for c in col) for col in colors])
            canvas.alpha_composite(label, (px + pw - 14 - label.width, py + 10))
        else:
            draw.text((px + pw - 22, py + 18), tier, font=num(18, "SemiBold"), fill=st["muted"], anchor="ra")
        number = _gradient_text(rating, num(84), [tuple(min(255, c + 40) for c in col) for col in colors])
        canvas.alpha_composite(number, (px + pw - 18 - number.width, py + ph - 14 - number.height))

    elif PLATE_STYLE == "bare":
        # no panel: large gradient number with a thin tier bar under it
        number = _gradient_text(rating, num(104), [tuple(min(255, c + 40) for c in col) for col in colors])
        nx, ny = right - number.width + 8, 62
        canvas.alpha_composite(number, (nx, ny))
        draw.text((right, 34), f"RATING  ·  {tier}", font=num(18, "SemiBold"), fill=st["muted"], anchor="ra")
        bar = _gradient_fill((number.width - 16, 5), colors)
        bar.putalpha(_rounded_mask(bar.size, 2))
        canvas.alpha_composite(bar, (right - bar.width, ny + number.height + 2))

    else:  # "stripe": dark panel with a tier-colored stripe on the left, white number
        pw, ph = 340, 132
        px, py = right - pw, 42
        panel = Image.new("RGBA", (pw, ph), (12, 10, 22, 215))
        stripe = _gradient_fill((14, ph), list(reversed(colors)))
        panel.paste(stripe, (0, 0))
        mask = _rounded_mask((pw, ph), 16)
        out = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        out.paste(panel, (0, 0), mask)
        canvas.alpha_composite(out, (px, py))
        draw.text((px + 32, py + 18), "RATING", font=num(18, "SemiBold"), fill=st["muted"])
        tier_img = _gradient_text(tier, num(18, "SemiBold"), [tuple(min(255, c + 40) for c in col) for col in colors])
        canvas.alpha_composite(tier_img, (px + pw - 12 - tier_img.width, py + 10))
        draw.text((px + pw - 20, py + ph - 12), rating, font=num(80), fill=(255, 255, 255), anchor="rd")


def _draw_section(canvas: Image.Image, y: int, title: str, sub: str, width: int, theme: dict, st: dict) -> int:
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((MARGIN, y + 22, MARGIN + 5, y + 46), fill=theme["accent"])
    draw.text((MARGIN + 16, y + 34), title, font=num(28), fill=st["text"], anchor="lm")
    tw = draw.textlength(title, font=num(28))
    draw.text((MARGIN + 28 + tw, y + 36), sub, font=num(18, "SemiBold"), fill=st["faint"], anchor="lm")
    line_x = MARGIN + 44 + tw + draw.textlength(sub, font=num(18, "SemiBold"))
    draw.line((line_x, y + 35, width - MARGIN, y + 35), fill=(*st["faint"], 90), width=1)
    return y + SECTION_H


def _radial_glows(size: tuple[int, int], glows, blur: int) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for (cx, cy, r, color) in glows:
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    return layer.filter(ImageFilter.GaussianBlur(blur))


def _stripes(size: tuple[int, int], color, spacing: int = 26) -> Image.Image:
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for off in range(-h, w, spacing):
        d.line((off, h, off + h, 0), fill=color, width=2)
    return layer


def _background(b50: B50, size: tuple[int, int], theme: dict, st: dict) -> Image.Image:
    w, h = size
    if st["bg"] == "light":
        base = _vertical_gradient(size, (252, 248, 255), (238, 242, 252)).convert("RGBA")
        pastel = [(255, 170, 210, 150), (150, 215, 255, 150), (255, 226, 150, 120), (200, 170, 255, 130)]
        glows = [(int(w * 0.1), int(h * 0.05), 420, pastel[0]), (int(w * 0.95), int(h * 0.15), 480, pastel[1]),
                 (int(w * 0.2), int(h * 0.75), 520, pastel[3]), (int(w * 0.85), int(h * 0.9), 460, pastel[2])]
        base.alpha_composite(_radial_glows(size, glows, 160))
        base.alpha_composite(_stripes(size, (255, 255, 255, 60)))
        return base

    if st["bg"] in ("collage", "collage_dim"):
        top = next((e.jacket_path for e in b50.old + b50.new if e.jacket_path), None)
        if top:
            with Image.open(top) as im:
                art = ImageOps.fit(im.convert("RGB"), size, Image.LANCZOS)
            dim = st["bg"] == "collage_dim"
            art = art.filter(ImageFilter.GaussianBlur(24 if dim else 6))
            art = Image.blend(art, Image.new("RGB", size, theme["bottom"]), 0.78 if dim else 0.5).convert("RGBA")
            shade = _vertical_gradient(size, (0, 0, 0), theme["bottom"]).convert("RGBA")
            shade.putalpha(Image.linear_gradient("L").resize(size).point(lambda v: 60 + v * 150 // 255))
            art.alpha_composite(shade)
            return art

    base = _vertical_gradient(size, theme["top"], theme["bottom"]).convert("RGBA")
    a = theme["accent"]
    glows = [(int(w * 0.08), 0, 520, (*a, 70)), (int(w * 0.9), int(h * 0.3), 560, (*theme["glow2"], 60)),
             (int(w * 0.3), int(h * 0.95), 600, (*theme["glow2"], 50))]
    base.alpha_composite(_radial_glows(size, glows, 200))
    base.alpha_composite(_stripes(size, (255, 255, 255, 7)))
    return base


def render_b50(b50: B50, now: datetime | None = None, style: str | None = None) -> bytes:
    theme = THEMES[b50.game]
    st = STYLES[style or os.environ.get("B50_STYLE", DEFAULT_STYLE)]
    old_slots, new_slots = SLOTS[b50.game]
    old_rows, new_rows = -(-old_slots // COLS), -(-new_slots // COLS)
    width = MARGIN * 2 + COLS * CARD_W + (COLS - 1) * GAP_X
    height = (HEADER_H + 2 * SECTION_H + (old_rows + new_rows) * (CARD_H + GAP_Y) + FOOTER_H)

    canvas = _background(b50, (width, height), theme, st)
    _draw_header(canvas, b50, width, theme, st)

    y = HEADER_H
    for title, sub, entries, rows in (
        (f"BEST {old_slots}", "OLD VERSIONS", b50.old, old_rows),
        (f"NEW {new_slots}", "CURRENT VERSION", b50.new, new_rows),
    ):
        y = _draw_section(canvas, y, title, sub, width, theme, st)
        for i, e in enumerate(entries):
            r, c = divmod(i, COLS)
            _draw_card(canvas, MARGIN + c * (CARD_W + GAP_X), y + r * (CARD_H + GAP_Y), i + 1, e, theme, st)
        y += rows * (CARD_H + GAP_Y)

    draw = ImageDraw.Draw(canvas)
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    source = f"{b50.source}  ·  " if b50.source else ""
    draw.text((width - MARGIN, height - 28), f"{source}{stamp}", font=num(17, "Medium"), fill=st["faint"], anchor="rm")

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
