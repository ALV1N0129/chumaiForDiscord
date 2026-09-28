"""Render the bot's images (B50, play logs, profile, song lists...)."""

from __future__ import annotations

import io
import os
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

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
    "mosaic": {"bg": "mosaic", "card": "jacket", "text": (255, 255, 255), "muted": (190, 194, 210),
               "faint": (150, 154, 172), "rank": (255, 206, 84)},
    "chara": {"bg": "chara", "card": "jacket", "text": (255, 255, 255), "muted": (190, 194, 210),
              "faint": (150, 154, 172), "rank": (255, 206, 84)},
    "version": {"bg": "version", "card": "jacket", "text": (255, 255, 255), "muted": (190, 194, 210),
                "faint": (150, 154, 172), "rank": (255, 206, 84)},
    "light": {"bg": "light", "card": "light", "text": (28, 28, 40), "muted": (92, 96, 116),
              "faint": (140, 144, 162), "rank": (214, 146, 0)},
}
DEFAULT_STYLE = "version"

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

# Output format. WebP is about a third of the PNG size, which matters on slow connections.
IMAGE_FORMAT = os.environ.get("IMAGE_FORMAT", "webp").lower()
_FORMATS = {"webp": ("WEBP", "webp", {"quality": 85, "method": 4}),
            "jpeg": ("JPEG", "jpg", {"quality": 88, "subsampling": 0, "optimize": True}),
            "png": ("PNG", "png", {"optimize": True})}
_FORMATS["jpg"] = _FORMATS["jpeg"]


def encode(image: Image.Image, fmt: str | None = None) -> bytes:
    name, _, opts = _FORMATS.get(fmt or IMAGE_FORMAT, _FORMATS["webp"])
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format=name, **opts)
    return buf.getvalue()


def filename(stem: str) -> str:
    """`stem` plus the extension of the output format, e.g. b50_maimai.webp."""
    return f"{stem}.{_FORMATS.get(IMAGE_FORMAT, _FORMATS['webp'])[1]}"

# ------------------------------------------------------------------ fonts

FONT_DIR = Path(os.environ.get("FONT_DIR", "data/fonts"))

# fonts with Korean *and* Japanese first; Windows' Japanese fonts have no Hangul
CJK_BOLD = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "C:/Windows/Fonts/malgunbd.ttf",
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
    return _first_existing([os.environ.get("FONT_PATH", ""), str(ASSETS / "fonts"),
                            str(FONT_DIR / "NotoSansCJKkr-Bold.otf"), *CJK_BOLD])


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
    ultima = label == "ULT"
    if ultima:  # in-game ULTIMA: black with a red rim
        draw.rounded_rectangle((jx - 5, jy - 5, jx + JACKET + 4, jy + JACKET + 4), radius=11, fill=(210, 20, 50))
        draw.rounded_rectangle((jx - 3, jy - 3, jx + JACKET + 2, jy + JACKET + 2), radius=9, fill=(12, 12, 14))
    else:
        draw.rounded_rectangle((jx - 3, jy - 3, jx + JACKET + 2, jy + JACKET + 2), radius=9, fill=color)
    jacket = _load_jacket(e.jacket_path) if e.jacket_path else None
    if jacket is None:
        jacket = Image.new("RGB", (JACKET, JACKET), (24, 24, 32))
        ImageDraw.Draw(jacket).text((JACKET // 2, JACKET // 2 - 8), "NO IMAGE", font=num(16, "SemiBold"),
                                    fill=FAINT, anchor="mm")
    canvas.paste(jacket, (jx, jy), _rounded_mask((JACKET, JACKET), 7))
    tag_h = 24
    draw.rectangle((jx, jy + JACKET - tag_h, jx + JACKET - 1, jy + JACKET - 1), fill=(12, 12, 14) if ultima else color)
    const = f"{e.level_const:.1f}" if e.level_const else e.level
    # light tags (Re:MASTER) need dark text; ULTIMA uses red on black
    tag_text = (255, 60, 80) if ultima else (60, 24, 96) if sum(color) > 560 else WHITE
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

    if st["bg"] == "version":
        # current version's key art: assets/backgrounds/<game>.(webp|png|jpg)
        for ext in ("webp", "png", "jpg"):
            path = ASSETS / "backgrounds" / f"{b50.game}.{ext}"
            if path.is_file():
                with Image.open(path) as im:
                    src = im.convert("RGB")
                lum = sum(ImageStat.Stat(src.convert("L")).mean) / 255
                dark = min(0.72, 0.45 + max(0.0, lum - 0.35) * 0.8)
                base = _vertical_gradient(size, theme["top"], theme["bottom"]).convert("RGBA")
                if src.width / src.height > w / h:
                    # wide key art: fit to the width at the top and fade it out downward
                    ah = round(src.height * w / src.width)
                    art = src.resize((w, ah), Image.LANCZOS)
                    blur = 2 if w / src.width < 2.5 else w / src.width
                    art = art.filter(ImageFilter.GaussianBlur(blur))
                    art = Image.blend(art, Image.new("RGB", art.size, theme["bottom"]), dark).convert("RGBA")
                    fade = Image.linear_gradient("L").resize((w, ah)).point(lambda v: 255 - max(0, v - 128) * 2)
                    art.putalpha(fade)
                    base.alpha_composite(art)
                    return base
                # small images get blurred more (hides upscaling artifacts), bright ones darkened more
                scale = max(w / src.width, h / src.height)
                art = ImageOps.fit(src, size, Image.LANCZOS, centering=(0.5, 0.0))
                art = art.filter(ImageFilter.GaussianBlur(3 if scale < 2.5 else scale * 2))
                art = Image.blend(art, Image.new("RGB", size, theme["bottom"]), dark).convert("RGBA")
                shade = Image.new("RGBA", size, (*theme["bottom"], 0))
                shade.putalpha(Image.linear_gradient("L").resize(size).point(lambda v: v * 120 // 255))
                art.alpha_composite(shade)
                return art

    if st["bg"] == "mosaic":
        paths = [e.jacket_path for e in b50.old + b50.new if e.jacket_path]
        if paths:
            tile = 150
            cols, rows = -(-w // tile) + 1, -(-h // tile)
            art = Image.new("RGB", (cols * tile, rows * tile))
            for i in range(cols * rows):
                j = _load_jacket(paths[i % len(paths)])
                if j is not None:
                    art.paste(j.resize((tile, tile)), ((i % cols) * tile - (tile // 2 if (i // cols) % 2 else 0),
                                                       (i // cols) * tile))
            art = art.crop((0, 0, w, h)).filter(ImageFilter.GaussianBlur(3))
            art = Image.blend(art, Image.new("RGB", size, theme["bottom"]), 0.82).convert("RGBA")
            art.alpha_composite(_stripes(size, (255, 255, 255, 6)))
            return art

    if st["bg"] == "chara" and b50.icon:
        base = _vertical_gradient(size, theme["top"], theme["bottom"]).convert("RGBA")
        icon = _open_image(b50.icon)
        if icon is not None:
            big = ImageOps.fit(icon.convert("RGB"), (h // 2, h // 2), Image.LANCZOS).convert("RGBA")
            big = big.resize((w // 2, w // 2)) if big.width < w // 2 else big
            fade = Image.linear_gradient("L").rotate(90).resize(big.size).point(lambda v: (255 - v) * 110 // 255)
            big.putalpha(fade)
            base.alpha_composite(big.filter(ImageFilter.GaussianBlur(2)), (w - big.width, 0))
            shade = Image.new("RGBA", size, (*theme["bottom"], 0))
            shade.putalpha(Image.linear_gradient("L").resize(size).point(lambda v: v * 200 // 255))
            base.alpha_composite(shade)
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

    return encode(canvas)


# ------------------------------------------------------------ play log card

ROW_H = 132


def _draw_play_badge(canvas: Image.Image, right: int, y: int, game: str, badge) -> None:
    """NEW (+improvement) / TIE / BEST <score>, right-aligned at `right`."""
    if badge.kind == "new":
        if badge.delta is None:
            text = "NEW"
        elif game == "maimai":
            text = f"NEW +{badge.delta:.4f}%"
        else:
            text = f"NEW +{int(badge.delta):,}"
        colors, fg = [(255, 120, 150), (255, 200, 90)], (40, 20, 30)
    elif badge.kind == "tie":
        text, colors, fg = "TIE", [(120, 200, 255), (160, 150, 255)], (20, 24, 44)
    else:
        best = f"{badge.best:.4f}%" if game == "maimai" else f"{int(badge.best):,}"
        text, colors, fg = f"BEST {best}", None, MUTED
    f = num(15)
    draw = ImageDraw.Draw(canvas)
    bw, bh = int(draw.textlength(text, font=f)) + 18, 20
    bx = right - bw
    if colors:
        pill = _gradient_fill((bw, bh), colors)
        pill.putalpha(_rounded_mask((bw, bh), 10))
    else:
        pill = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        pill.paste(Image.new("RGBA", (bw, bh), (8, 8, 16, 170)), (0, 0), _rounded_mask((bw, bh), 10))
    canvas.alpha_composite(pill, (bx, y))
    ImageDraw.Draw(canvas).text((bx + bw // 2, y + bh // 2), text, font=f, fill=fg, anchor="mm")


def _draw_credit_summary(canvas: Image.Image, box: tuple[int, int, int, int], game: str, entries: list[Entry],
                         badges: list, theme: dict) -> None:
    """Tracks played, new records and the average song rating, as a card in an unplayed slot."""
    x0, y0, x1, y1 = box
    _panel(canvas, box, theme["card"], alpha=200, radius=RADIUS)
    draw = ImageDraw.Draw(canvas)
    draw.text((x0 + 18, y0 + 16), "CREDIT", font=num(16, "SemiBold"), fill=theme["accent"])
    ratings = [e.rating for e in entries]
    avg = sum(ratings) / len(ratings)
    new = sum(1 for b in badges if b is not None and b.kind == "new")
    stats = [
        ("TRACKS", str(len(entries)), WHITE),
        ("NEW RECORD", str(new), (255, 200, 120) if new else WHITE),
        ("AVG RATING", f"{float(avg):.0f}" if game == "maimai" else f"{float(avg):.2f}", WHITE),
    ]
    col = (x1 - x0 - 36) / len(stats)
    for k, (label, value, color) in enumerate(stats):
        cx = x0 + 18 + col * k
        draw.text((cx, y1 - 26), label, font=num(14, "SemiBold"), fill=MUTED, anchor="ls")
        draw.text((cx, y1 - 42), value, font=num(38), fill=color, anchor="ls")


def render_credit(game: str, player: str, entries: list[Entry], badges: list, date: str,
                  icon: bytes | None = None, rating: str | None = None) -> bytes:
    """One credit as a fixed-size 2x2 grid, so every credit shows at the same size in Discord.

    badges: a playlog.Badge (or None) per entry.
    """
    from types import SimpleNamespace

    theme = THEMES[game]
    st = STYLES["version"]
    cols, slots = 2, 4
    header = 118
    width = MARGIN * 2 + cols * CARD_W + (cols - 1) * GAP_X
    height = header + (slots // cols) * (CARD_H + GAP_Y) + 26
    stub = SimpleNamespace(game=game, old=entries, new=[], icon=icon)
    canvas = _background(stub, (width, height), theme, st)
    draw = ImageDraw.Draw(canvas)

    x = MARGIN
    ic = _open_image(icon)
    if ic is not None:
        ic = ImageOps.fit(ic, (64, 64), Image.LANCZOS)
        out = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        out.paste(ic, (0, 0), _rounded_mask((64, 64), 12))
        canvas.alpha_composite(out, (x, 30))
        x += 80
    draw.text((x, 30), f"{GAME_NAMES[game].upper()}  PLAY LOG  ·  {date}", font=num(17, "SemiBold"),
              fill=theme["accent"])
    name = unicodedata.normalize("NFKC", player)
    draw.text((x, 52), _fit(draw, name, cjk(34), 420), font=cjk(34), fill=WHITE)

    right = width - MARGIN
    if rating:
        colors = _plate_colors(game, rating)
        number = _gradient_text(rating, num(50), [tuple(min(255, c + 40) for c in col) for col in colors])
        canvas.alpha_composite(number, (right - number.width + 8, 44))
        draw.text((right, 24), "RATING", font=num(15, "SemiBold"), fill=st["muted"], anchor="ra")
        right -= number.width + 10
    if len(entries) >= 4:  # extra track bought with C to C
        bw, bh = 78, 26
        bx, by = right - bw, 56
        badge = _gradient_fill((bw, bh), [theme["accent"], theme["glow2"]])
        badge.putalpha(_rounded_mask((bw, bh), 13))
        canvas.alpha_composite(badge, (bx, by))
        draw.text((bx + bw // 2, by + bh // 2), "C to C", font=num(17), fill=(20, 18, 30), anchor="mm")

    # an unplayed slot shows a summary of the credit instead of an empty card
    summary_at = {1: 1, 2: 2, 3: 3}.get(len(entries), -1)
    for i in range(slots):
        r, c = divmod(i, cols)
        cx, cy = MARGIN + c * (CARD_W + GAP_X), header + r * (CARD_H + GAP_Y)
        if i >= len(entries) and i == summary_at:
            if len(entries) == 2:  # the whole second row
                box = (cx, cy, cx + 2 * CARD_W + GAP_X, cy + CARD_H)
            else:
                box = (cx, cy, cx + CARD_W, cy + CARD_H)
            _draw_credit_summary(canvas, box, game, entries, badges, theme)
            continue
        if i >= len(entries):
            if len(entries) == 2:
                continue  # covered by the summary
            empty = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
            empty.paste(Image.new("RGBA", (CARD_W, CARD_H), (10, 8, 18, 90)), (0, 0), _rounded_mask((CARD_W, CARD_H), RADIUS))
            canvas.alpha_composite(empty, (cx, cy))
            draw.text((cx + CARD_W // 2, cy + CARD_H // 2), f"TRACK {i + 1}", font=num(20, "SemiBold"),
                      fill=(110, 112, 130), anchor="mm")
            continue
        _draw_card(canvas, cx, cy, i + 1, entries[i], theme, st)
        if badges[i] is not None:
            _draw_play_badge(canvas, cx + CARD_W - 14, cy + 40, game, badges[i])
        draw = ImageDraw.Draw(canvas)

    return encode(canvas)


# ---------------------------------------------------------------- profile


def render_profile(game: str, name: str, rating: str | None, title: str | None, title_rarity: str | None,
                   level: str | None, icon: bytes | None, plate: bytes | None) -> bytes:
    """Profile card: nameplate, icon, title, level, name and the rating plate."""
    from types import SimpleNamespace

    theme = THEMES[game]
    st = STYLES["version"]
    width, height = MARGIN * 2 + 2 * CARD_W + GAP_X, 220
    canvas = _background(SimpleNamespace(game=game, old=[], new=[], icon=icon), (width, height), theme, st)

    cw, ch = width - MARGIN * 2 - 360, 150
    cx, cy = MARGIN, 36
    nameplate = _open_image(plate)
    if nameplate is not None:
        bg = ImageOps.fit(nameplate.convert("RGB"), (cw, ch), Image.LANCZOS).convert("RGBA")
        shade = Image.new("RGBA", (cw, ch), (8, 6, 16, 0))
        shade.putalpha(Image.linear_gradient("L").resize((cw, ch)).point(lambda v: max(0, v - 60) * 170 // 195))
        bg.alpha_composite(shade)
    else:
        bg = Image.new("RGBA", (cw, ch), (*theme["card"], 235))
    card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    card.paste(bg, (0, 0), _rounded_mask((cw, ch), 18))
    ImageDraw.Draw(card).rounded_rectangle((0, 0, cw - 1, ch - 1), radius=18, outline=(255, 255, 255, 60), width=2)
    canvas.alpha_composite(card, (cx, cy))
    draw = ImageDraw.Draw(canvas)

    tx, right = cx + 20, cx + cw - 16
    ic = _open_image(icon)
    if ic is not None:
        size = ch - 28
        ic = ImageOps.fit(ic, (size, size), Image.LANCZOS)
        framed = Image.new("RGBA", (size, size), (20, 18, 30, 255))
        framed.alpha_composite(ic)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(framed, (0, 0), _rounded_mask((size, size), 14))
        canvas.alpha_composite(out, (right - size, cy + 14))
        right -= size + 16

    if title:
        colors = TITLE_COLORS.get((title_rarity or "normal").lower(), TITLE_COLORS["normal"])
        t = _fit(draw, title, cjk(16), right - tx - 40)
        tw = int(draw.textlength(t, font=cjk(16))) + 40
        rim = _gradient_fill((tw, 30), colors)
        rim.putalpha(_rounded_mask((tw, 30), 15))
        canvas.alpha_composite(rim, (tx, cy + 16))
        core = Image.new("RGBA", (tw - 4, 26), (0, 0, 0, 0))
        core.paste(Image.new("RGBA", core.size, (14, 12, 24, 215)), (0, 0), _rounded_mask(core.size, 13))
        canvas.alpha_composite(core, (tx + 2, cy + 18))
        draw.text((tx + tw // 2, cy + 31), t, font=cjk(16), fill=WHITE, anchor="mm")

    base = cy + ch - 26
    nx = tx
    if level:
        lv = f"Lv.{level}"
        draw.text((nx, base), lv, font=num(26, "SemiBold"), fill=(235, 235, 245), anchor="ls",
                  stroke_width=2, stroke_fill=(10, 8, 18))
        nx += draw.textlength(lv, font=num(26, "SemiBold")) + 16
    shown = unicodedata.normalize("NFKC", name)
    draw.text((nx, base + 2), _fit(draw, shown, cjk(44), right - nx), font=cjk(44), fill=WHITE, anchor="ls",
              stroke_width=3, stroke_fill=(10, 8, 18))

    if rating:
        _draw_plate(canvas, game, rating, width, st)

    return encode(canvas)


# ------------------------------------------------------- song / list pages

DIFF_FULL = {"BAS": "BASIC", "ADV": "ADVANCED", "EXP": "EXPERT", "MAS": "MASTER", "Re:M": "Re:MASTER",
             "ULT": "ULTIMA", "WE": "WORLD'S END"}
ULTIMA_RIM = (210, 20, 50)


def _page(game: str, size: tuple[int, int]) -> Image.Image:
    from types import SimpleNamespace

    return _background(SimpleNamespace(game=game, old=[], new=[], icon=None), size, THEMES[game], STYLES["version"])


def _page_header(canvas: Image.Image, game: str, kicker: str, title: str, sub: str | None = None) -> None:
    draw = ImageDraw.Draw(canvas)
    draw.text((MARGIN, 30), f"{GAME_NAMES[game].upper()}  {kicker}", font=num(18, "SemiBold"),
              fill=THEMES[game]["accent"])
    draw.text((MARGIN, 52), title, font=num(40), fill=WHITE)
    if sub:
        x = MARGIN + draw.textlength(title, font=num(40)) + 16
        draw.text((x, 88), sub, font=cjk(17), fill=MUTED, anchor="ls")


def _panel(canvas: Image.Image, box: tuple[int, int, int, int], color, alpha: int = 235, radius: int = 18,
           outline: bool = True) -> None:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    panel.paste(Image.new("RGBA", (w, h), (*color, alpha)), (0, 0), _rounded_mask((w, h), radius))
    if outline:
        ImageDraw.Draw(panel).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, outline=(255, 255, 255, 40),
                                                width=2)
    canvas.alpha_composite(panel, (x0, y0))


def _diff_info(difficulty: str) -> tuple[str, str, tuple[int, int, int], bool]:
    """(short label, full name, color, is DX chart)"""
    from types import SimpleNamespace

    label, color, is_dx = _diff(SimpleNamespace(difficulty=difficulty))
    return label, ("DX " if is_dx else "") + DIFF_FULL.get(label, label), color, is_dx


def _framed_jacket(canvas: Image.Image, x: int, y: int, size: int, path, difficulty: str | None,
                   rim: tuple[int, int, int] | None = None) -> None:
    """Jacket with a difficulty-colored frame (ULTIMA: black with a red rim) and a DX badge."""
    draw = ImageDraw.Draw(canvas)
    pad = max(3, size // 56)
    radius = max(6, size // 22)
    label, _, color, is_dx = _diff_info(difficulty) if difficulty else ("", "", rim or (60, 60, 80), False)
    if label == "ULT":
        draw.rounded_rectangle((x - pad - 2, y - pad - 2, x + size + pad + 1, y + size + pad + 1),
                               radius=radius + 4, fill=ULTIMA_RIM)
        color = (12, 12, 14)
    draw.rounded_rectangle((x - pad, y - pad, x + size + pad - 1, y + size + pad - 1), radius=radius + 2, fill=color)
    jacket = None
    if path:
        try:
            with Image.open(path) as im:
                jacket = ImageOps.fit(im.convert("RGB"), (size, size), Image.LANCZOS)
        except Exception:
            jacket = None
    if jacket is None:
        jacket = Image.new("RGB", (size, size), (24, 24, 32))
        if size >= 80:
            ImageDraw.Draw(jacket).text((size // 2, size // 2), "NO IMAGE", font=num(max(12, size // 10), "SemiBold"),
                                        fill=FAINT, anchor="mm")
    canvas.paste(jacket, (x, y), _rounded_mask((size, size), radius))
    if is_dx and size >= 60:
        s = size / 228
        bw, bh = max(24, round(36 * s)), max(15, round(22 * s))
        draw.rounded_rectangle((x + 6, y + 6, x + 6 + bw, y + 6 + bh), radius=4, fill=WHITE)
        draw.text((x + 6 + bw / 2, y + 6 + bh / 2), "DX", font=num(max(12, round(18 * s))), fill=(230, 70, 110),
                  anchor="mm")


def _diff_bar(canvas: Image.Image, box: tuple[int, int, int, int], difficulty: str, right: str,
              size: int = 20) -> None:
    """Colored pill: difficulty name on the left, `right` (level / constant) on the right."""
    draw = ImageDraw.Draw(canvas)
    label, name, color, _ = _diff_info(difficulty)
    ultima = label == "ULT"
    fill = (12, 12, 14) if ultima else color
    text = (255, 60, 80) if ultima else (60, 24, 96) if sum(color) > 560 else WHITE
    x0, y0, x1, y1 = box
    r = (y1 - y0) // 4
    if ultima:
        draw.rounded_rectangle(box, radius=r, fill=ULTIMA_RIM)
        draw.rounded_rectangle((x0 + 2, y0 + 2, x1 - 2, y1 - 2), radius=r, fill=fill)
    else:
        draw.rounded_rectangle(box, radius=r, fill=fill)
    cy = (y0 + y1) // 2
    draw.text((x0 + 10, cy), name, font=num(size), fill=text, anchor="lm")
    font = num(size + 4) if right.isascii() else cjk(size)  # WORLD'S END levels look like 招☆4
    draw.text((x1 - 10, cy), right, font=font, fill=text, anchor="rm")


def _chip(canvas: Image.Image, x: int, y: int, text: str, size: int = 14) -> int:
    """Small translucent label. Returns its width."""
    draw = ImageDraw.Draw(canvas)
    w = int(draw.textlength(text, font=cjk(size))) + 20
    h = size + 12
    _panel(canvas, (x, y, x + w, y + h), (255, 255, 255), alpha=30, radius=h // 2, outline=False)
    ImageDraw.Draw(canvas).text((x + w // 2, y + h // 2), text, font=cjk(size), fill=MUTED, anchor="mm")
    return w


def _const_text(level: str, const: float) -> str:
    return f"{level}  {const:.1f}" if const else level


# ------------------------------------------------------------ random picks

PICK_W, PICK_JACKET = 260, 228


def _wrap(draw: ImageDraw.ImageDraw, text: str, f, width: int, max_lines: int) -> list[str]:
    lines, line = [], ""
    for ch in text:
        if draw.textlength(line + ch, font=f) > width:
            lines.append(line)
            line = ch.lstrip()
            if len(lines) == max_lines:
                break
        else:
            line += ch
    else:
        lines.append(line)
        return lines
    lines[-1] = _fit(draw, lines[-1] + line, f, width)
    return lines


def render_random(game: str, picks: list[dict], level_label: str) -> bytes:
    """Random picks as tall cards side by side.

    Each pick: title, artist, genre, difficulty, level, const, jacket (path or None).
    """
    theme = THEMES[game]
    gap, header, card_h = 18, 104, 432
    width = MARGIN * 2 + len(picks) * PICK_W + (len(picks) - 1) * gap
    width = max(width, 560)
    height = header + card_h + 34
    canvas = _page(game, (width, height))
    _page_header(canvas, game, "RANDOM", level_label)

    x0 = (width - (len(picks) * PICK_W + (len(picks) - 1) * gap)) // 2
    for i, p in enumerate(picks):
        x, y = x0 + i * (PICK_W + gap), header
        _panel(canvas, (x, y, x + PICK_W, y + card_h), theme["card"])
        jx, jy = x + (PICK_W - PICK_JACKET) // 2, y + 16
        _framed_jacket(canvas, jx, jy, PICK_JACKET, p.get("jacket"), p["difficulty"])
        by = jy + PICK_JACKET + 14
        _diff_bar(canvas, (jx - 4, by, jx + PICK_JACKET + 3, by + 40), p["difficulty"],
                  _const_text(p["level"], p["const"]))

        draw = ImageDraw.Draw(canvas)
        ty = by + 54
        for line in _wrap(draw, p["title"], cjk(20), PICK_W - 32, 2):
            draw.text((x + 16, ty), line, font=cjk(20), fill=WHITE)
            ty += 27
        draw.text((x + 16, ty + 2), _fit(draw, p.get("artist") or "", cjk(15), PICK_W - 32), font=cjk(15),
                  fill=MUTED)
        if p.get("genre"):
            _chip(canvas, x + 16, y + card_h - 38, p["genre"], 13)
    return encode(canvas)


# --------------------------------------------------------------- song info


def render_song(game: str, song: dict, charts: list[dict], jacket) -> bytes:
    """One song: big jacket, title/artist/genre/version and a bar per chart.

    song: title, artist, genre, versions (list); charts: difficulty, level, const.
    """
    theme = THEMES[game]
    width, js = 960, 300
    tx = MARGIN + js + 40
    tw = width - tx - MARGIN
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_lines = _wrap(probe, song["title"], cjk(34), tw, 2)
    bars_y = 104 + len(title_lines) * 44 + 34 + 48
    bar_h, bar_gap = 46, 10
    bars_end = bars_y + len(charts) * (bar_h + bar_gap)
    height = max(104 + js + 24, bars_end) + 36
    canvas = _page(game, (width, height))
    _page_header(canvas, game, "SONG", "")
    _panel(canvas, (MARGIN - 16, 84, width - MARGIN + 16, height - 20), theme["card"], alpha=215)

    _framed_jacket(canvas, MARGIN + 4, 108, js - 8, jacket, None, rim=theme["accent"])

    draw = ImageDraw.Draw(canvas)
    y = 104
    for line in title_lines:
        draw.text((tx, y), line, font=cjk(34), fill=WHITE)
        y += 44
    draw.text((tx, y + 2), _fit(draw, song.get("artist") or "", cjk(19), tw), font=cjk(19), fill=MUTED)
    cx = tx
    for text in [song.get("genre")] + list(song.get("versions") or [])[-2:]:
        if text:
            cx += _chip(canvas, cx, y + 38, text) + 8

    for i, c in enumerate(charts):
        by = bars_y + i * (bar_h + bar_gap)
        _diff_bar(canvas, (tx, by, width - MARGIN, by + bar_h), c["difficulty"], _const_text(c["level"], c["const"]),
                  size=22)
    return encode(canvas)


# -------------------------------------------------------------- chart lists


def render_chart_list(game: str, kicker: str, title: str, rows: list[dict], sub: str | None = None,
                      footer: str | None = None, columns: int = 3, group: bool = False) -> bytes:
    """Charts as tiles: jacket, title, difficulty/level and a value on the right.

    rows: title, difficulty, level, const, jacket, right (big text), and optionally right_sub (small text
    under it), sub_line (after the difficulty), note (a line along the bottom of the tile) and genre
    (a chip at the end of the note).
    group=True puts a heading above each run of charts with the same constant.
    """
    theme = THEMES[game]
    big = columns <= 2
    tile_w = 560 if big else 380
    top_h = 96 if big else 72
    note_h = 40 if any(r.get("note") for r in rows) else 0
    tile_h = top_h + note_h
    js = top_h - 20
    gap = 12
    width = MARGIN * 2 + columns * tile_w + (columns - 1) * gap

    # lay out: (kind, y, payload)
    items: list[tuple[str, int, int, object]] = []
    y, col, last = 116, 0, None
    for row in rows:
        if group and row["const"] != last:
            if col:
                y += tile_h + gap
                col = 0
            items.append(("head", MARGIN, y, f"{row['const']:.1f}"))
            y += 40
            last = row["const"]
        items.append(("tile", MARGIN + col * (tile_w + gap), y, row))
        col += 1
        if col == columns:
            col = 0
            y += tile_h + gap
    if col:
        y += tile_h + gap
    height = y + (44 if footer else 20)

    canvas = _page(game, (width, height))
    _page_header(canvas, game, kicker, title, sub)
    for kind, x, y, payload in items:
        draw = ImageDraw.Draw(canvas)
        if kind == "head":
            draw.text((x + 2, y + 18), str(payload), font=num(28), fill=theme["accent"], anchor="lm")
            lw = draw.textlength(str(payload), font=num(28)) + 14
            draw.line((x + lw, y + 19, width - MARGIN, y + 19), fill=(255, 255, 255, 50), width=1)
            continue
        row = payload
        _panel(canvas, (x, y, x + tile_w, y + tile_h), theme["card"], radius=14)
        _framed_jacket(canvas, x + 12, y + 10, js, row.get("jacket"), row["difficulty"])
        draw = ImageDraw.Draw(canvas)
        label, name, color, _ = _diff_info(row["difficulty"])
        right = row.get("right") or ""
        rw = int(draw.textlength(right, font=num(34 if big else 26))) + 20 if right else 0
        tx = x + 12 + js + 16
        text_w = x + tile_w - tx - rw - 8
        tsize = 20 if big else 17
        draw.text((tx, y + (22 if big else 14)), _fit(draw, row["title"], cjk(tsize), text_w), font=cjk(tsize),
                  fill=WHITE)
        dcolor = (255, 80, 100) if label == "ULT" else tuple(min(255, v + 50) for v in color)
        info = f"{name}  {_const_text(row['level'], row['const'])}" if big else \
            f"{('DX ' if name.startswith('DX') else '') + label}  {row['level']}"
        info_font = num(19 if big else 17, "SemiBold")
        info_y = y + top_h - (24 if big else 16)
        draw.text((tx, info_y), info, font=info_font, fill=dcolor, anchor="ls")
        if row.get("sub_line"):
            sx = tx + draw.textlength(info, font=info_font) + 12
            draw.text((sx, info_y), _fit(draw, row["sub_line"], cjk(14), max(0, text_w - int(sx - tx))),
                      font=cjk(14), fill=MUTED, anchor="ls")
        if right:
            if row.get("right_sub"):
                draw.text((x + tile_w - 16, y + top_h / 2 - 2), right, font=num(34), fill=MAX_RATING, anchor="rs")
                sub_font = num(17, "Medium") if row["right_sub"].isascii() else cjk(14)
                draw.text((x + tile_w - 16, y + top_h / 2 + 22), row["right_sub"], font=sub_font, fill=MUTED,
                          anchor="rs")
            else:
                draw.text((x + tile_w - 14, y + top_h / 2), right, font=num(34 if big else 26), fill=WHITE,
                          anchor="rm")
        if row.get("note"):
            ny = y + top_h
            _panel(canvas, (x + 10, ny, x + tile_w - 10, ny + note_h - 10), (0, 0, 0), alpha=70, radius=10,
                   outline=False)
            draw = ImageDraw.Draw(canvas)
            note_w = tile_w - 44
            if row.get("genre"):  # the in-game folder, to find the song quickly
                gw = int(draw.textlength(row["genre"], font=cjk(13))) + 18
                gx, gy = x + tile_w - 16 - gw, ny + (note_h - 10) // 2 - 11
                _panel(canvas, (gx, gy, gx + gw, gy + 22), theme["accent"], alpha=45, radius=11, outline=False)
                draw = ImageDraw.Draw(canvas)
                draw.text((gx + gw // 2, gy + 11), row["genre"], font=cjk(13), fill=WHITE, anchor="mm")
                note_w -= gw + 10
            draw.text((x + 22, ny + (note_h - 10) // 2), _fit(draw, row["note"], cjk(14), note_w), font=cjk(14),
                      fill=MUTED, anchor="lm")
    if footer:
        ImageDraw.Draw(canvas).text((width - MARGIN, height - 26), footer, font=cjk(15), fill=MUTED, anchor="rm")
    return encode(canvas)


# ------------------------------------------------------------- calculations


def render_scores(game: str, kicker: str, headline: str, detail: str, rows: list[tuple[str, str, str, bool]],
                  chart: dict | None = None, note: str | None = None) -> bytes:
    """A result card: big headline, a line of detail and a score -> rating table.

    rows: (score, rank, rating, highlight). chart (optional): title, difficulty, level, const, jacket.
    """
    theme = THEMES[game]
    width = 760
    top = 84
    card_top = top
    chart_h = 124 if chart else 0
    head_y = card_top + chart_h + 22
    table_y = head_y + 104
    row_h = 40
    height = table_y + len(rows) * row_h + (44 if note else 18) + 30
    canvas = _page(game, (width, height))
    _page_header(canvas, game, kicker, "")
    _panel(canvas, (MARGIN - 16, card_top, width - MARGIN + 16, height - 24), theme["card"], alpha=225)
    draw = ImageDraw.Draw(canvas)

    if chart:
        js = 96
        _framed_jacket(canvas, MARGIN + 6, card_top + 18, js, chart.get("jacket"), chart["difficulty"])
        tx = MARGIN + 6 + js + 22
        draw = ImageDraw.Draw(canvas)
        draw.text((tx, card_top + 26), _fit(draw, chart["title"], cjk(24), width - MARGIN - tx), font=cjk(24),
                  fill=WHITE)
        _diff_bar(canvas, (tx, card_top + 70, min(width - MARGIN, tx + 330), card_top + 106), chart["difficulty"],
                  _const_text(chart["level"], chart["const"]), size=18)
        draw = ImageDraw.Draw(canvas)
        draw.line((MARGIN, card_top + chart_h + 8, width - MARGIN, card_top + chart_h + 8),
                  fill=(255, 255, 255, 40), width=1)

    draw.text((MARGIN + 4, head_y + 40), headline, font=num(54), fill=MAX_RATING, anchor="ls")
    draw.text((MARGIN + 4, head_y + 76), detail, font=cjk(18), fill=MUTED, anchor="ls")

    for i, (score, rank, value, hl) in enumerate(rows):
        y = table_y + i * row_h
        if hl:
            _panel(canvas, (MARGIN - 4, y, width - MARGIN + 4, y + row_h - 4), theme["accent"], alpha=40, radius=10,
                   outline=False)
        draw = ImageDraw.Draw(canvas)
        c = WHITE if hl else MUTED
        draw.text((MARGIN + 10, y + 18), score, font=num(24, "SemiBold"), fill=c, anchor="lm")
        draw.text((width // 2, y + 18), rank, font=num(22, "SemiBold"), fill=RANK_COLORS.get(rank, c), anchor="mm")
        draw.text((width - MARGIN - 10, y + 18), value, font=num(26), fill=c, anchor="rm")
    if note:
        draw.text((MARGIN + 4, height - 50), note, font=cjk(15), fill=FAINT)
    return encode(canvas)
