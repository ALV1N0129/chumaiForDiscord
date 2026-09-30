"""Render the bot's images (B50, play logs, profile, song lists...)."""

from __future__ import annotations

import io
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

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
    "utage": ("宴", (208, 8, 176)),  # maimai DX NET's U·TA·GE magenta
}

# CHUNITHM-NET's WORLD'S END label (musiclevel_worldsend.png, 140x20): bands leaning "/" (0.9 height
# across per height down), each 1.8 heights wide (red half that), in this order
WE_BANDS = [((12, 110, 243), 1.8), ((96, 180, 89), 1.8), ((226, 176, 5), 1.8), ((211, 40, 30), 0.9),
            ((215, 8, 144), 1.8)]
WE_TEXT = (249, 249, 219)  # the label's cream letters
WE_OUTLINE = (60, 40, 70)


@lru_cache(maxsize=4)
def _we_texture(w: int, h: int) -> Image.Image:
    """w x h of the WORLD'S END label's bands, scaled to the width as on the label (all five colors
    across, the first blue band cut at the left edge)."""
    unit = w / 7  # the label is 7 times wider than tall
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    slant = 0.9 * h  # the bands move this far left from top to bottom
    x = -0.7 * unit
    while x < w + slant:
        for color, width in WE_BANDS:
            bw = width * unit
            draw.polygon([(x - slant, h), (x + bw - slant, h), (x + bw, 0), (x, 0)], fill=color)
            x += bw
    return img


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
# Rating colors per tier, top to bottom. CHUNITHM: sampled from CHUNITHM-NET's rating digits
# (images/rating/rating_<tier>_XX.png), which shade each digit from top to bottom (the metal tiers
# have a bright band in the middle); 虹 from 16.00, the more colorful 虹(極) from 17.00.
# maimai: the colors of maimai DX NET's rating plates (img/rating_base_<tier>.png).
CHUNI_RAINBOW = [(240, 156, 135), (232, 236, 90), (135, 234, 70), (95, 232, 170), (50, 236, 232)]
CHUNI_KIWAMI = [(232, 208, 121), (242, 138, 122), (240, 40, 190), (160, 40, 228), (30, 130, 238),
                (0, 205, 222), (0, 238, 200)]
MAI_RAINBOW = [(255, 140, 140), (255, 215, 110), (160, 240, 140), (120, 200, 255), (215, 150, 255)]
PLATES = {
    "maimai": [
        (16000, MAI_RAINBOW),
        (15000, MAI_RAINBOW),
        (14500, [(255, 250, 190), (245, 215, 100)]),  # platinum
        (14000, [(255, 232, 70), (250, 180, 0)]),  # gold
        (13000, [(205, 232, 246), (125, 172, 208)]),  # silver
        (12000, [(214, 125, 88), (145, 62, 42)]),  # bronze
        (10000, [(222, 152, 255), (170, 70, 245)]),  # purple
        (7000, [(255, 140, 140), (215, 60, 70)]),  # red
        (4000, [(255, 212, 60), (245, 135, 10)]),  # orange
        (2000, [(178, 240, 112), (80, 195, 50)]),  # green
        (1000, [(122, 215, 255), (60, 150, 240)]),  # blue
        (0, [(238, 242, 248), (190, 200, 215)]),  # white
    ],
    "chunithm": [
        (17.0, CHUNI_KIWAMI),
        (16.0, CHUNI_RAINBOW),
        (15.25, [(218, 209, 172), (244, 244, 244), (217, 199, 148), (221, 215, 197)]),  # platinum
        (14.5, [(214, 183, 52), (245, 235, 129), (226, 193, 59), (221, 204, 111)]),  # gold
        (13.25, [(142, 201, 217), (199, 243, 244), (141, 199, 216), (175, 214, 220)]),  # silver
        (12.0, [(207, 103, 11), (245, 173, 44), (207, 101, 7), (223, 144, 46)]),  # bronze
        (10.0, [(218, 96, 205), (233, 99, 218), (200, 70, 192)]),  # purple
        (7.0, [(228, 90, 104), (233, 88, 104), (209, 60, 80)]),  # red
        (4.0, [(225, 168, 6), (240, 183, 6), (226, 166, 2)]),  # orange
        (0, [(110, 225, 50), (75, 235, 35), (45, 212, 22)]),  # green
    ],
}

GAME_NAMES = {"maimai": "maimai DX", "chunithm": "CHUNITHM"}

# LOW_MEMORY=1 (small hosts, e.g. 128MB): the B50 is drawn at 60% size (B50_SCALE to change it),
# /const and /recommend at 70%, which needs about half the memory. Everything else looks the same.
LOW_MEMORY = os.environ.get("LOW_MEMORY", "").strip().lower() in {"1", "true", "yes", "on"}
_scale_env = os.environ.get("B50_SCALE", "").strip()
B50_SCALE = float(_scale_env) if _scale_env else (0.6 if LOW_MEMORY else 1.0)  # e.g. B50_SCALE=0.7
LIST_SCALE = min(B50_SCALE, 0.7) if LOW_MEMORY else 1.0  # /const and /recommend

# Output format. WebP is about a third of the PNG size, which matters on slow connections.
IMAGE_FORMAT = os.environ.get("IMAGE_FORMAT", "webp").lower()
# WebP method 2: about the same size as 4, half the time and a quarter less memory
_FORMATS = {"webp": ("WEBP", "webp", {"quality": 85, "method": 2}),
            "jpeg": ("JPEG", "jpg", {"quality": 88, "subsampling": 0, "optimize": True}),
            "png": ("PNG", "png", {"optimize": True})}
_FORMATS["jpg"] = _FORMATS["jpeg"]


def encode(image: Image.Image, fmt: str | None = None) -> bytes:
    """Encode for Discord. The image is closed afterwards (its memory is freed right away)."""
    name, _, opts = _FORMATS.get(fmt or IMAGE_FORMAT, _FORMATS["webp"])
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    if rgb is not image:
        image.close()  # free the RGBA canvas before the encoder allocates its buffers
    buf = io.BytesIO()
    rgb.save(buf, format=name, **opts)
    rgb.close()
    return buf.getvalue()


def tune_malloc() -> None:
    """glibc: return big image buffers to the OS as soon as they are freed.

    By default glibc raises its mmap threshold after a big buffer is freed, so the next page-sized
    buffers come from the heap and the memory is never given back; fixing the threshold (and
    capping per-thread arenas, renders run in worker threads) keeps the resident size near idle.
    """
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6")
        libc.mallopt(-3, 256 * 1024)  # M_MMAP_THRESHOLD
        libc.mallopt(-8, 2)  # M_ARENA_MAX
    except Exception:
        pass  # not glibc (Windows / macOS)


def release_memory() -> None:
    """Hand freed memory back to the OS (glibc keeps it otherwise, so the peak would stick)."""
    import gc

    # drawn jackets and card backgrounds are cheap to make again; kept, they hold MBs between images
    _load_jacket.cache_clear()
    _card_background.cache_clear()
    gc.collect()
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass  # not glibc (Windows / macOS)


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


@lru_cache(maxsize=3 if LOW_MEMORY else 6)  # each size of the CJK font holds ~2MB, so keep only a few
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


def _vertical_gradient(size: tuple[int, int], top, bottom, mode: str = "RGB") -> Image.Image:
    w, h = size
    col = Image.new(mode, (1, h))
    extra = (255,) if mode == "RGBA" else ()
    for y in range(h):
        t = y / max(1, h - 1)
        col.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + extra)
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


def _rgb(im: Image.Image) -> Image.Image:
    """The page canvas: RGB (the page is opaque; drawing on RGB saves a quarter of the memory)."""
    if im.mode == "RGB":
        return im
    out = im.convert("RGB")
    im.close()
    return out


def _over(canvas: Image.Image, im: Image.Image, dest: tuple[int, int] = (0, 0)) -> None:
    """Draw `im` over the canvas at `dest`, blending by its alpha.

    Canvases are RGB (a quarter smaller than RGBA, and saved without a copy); pasting through the
    image's own alpha gives the same result as alpha_composite on an opaque canvas.
    """
    dest = (int(dest[0]), int(dest[1]))
    if canvas.mode == "RGBA":
        canvas.alpha_composite(im, dest)
    elif im.mode in ("RGBA", "LA"):
        canvas.paste(im, dest, im)
    else:
        canvas.paste(im, dest)


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _diff(e: Entry) -> tuple[str, tuple[int, int, int], bool]:
    d = e.difficulty.lower()
    is_dx = d.startswith("dx ")
    label, color = DIFFS.get(d[3:] if is_dx else d, (e.difficulty[:4].upper(), (110, 110, 110)))
    return label, color, is_dx


@lru_cache(maxsize=8 if LOW_MEMORY else 64)  # a B50 uses each jacket once
def _load_jacket(path: str) -> Image.Image | None:
    try:
        with Image.open(path) as im:
            return ImageOps.fit(im.convert("RGB"), (JACKET, JACKET), Image.LANCZOS)
    except Exception:
        return None


@lru_cache(maxsize=4 if LOW_MEMORY else 16)
def _card_background(path: str | None, mode: str, fallback: tuple[int, int, int],
                     size: tuple[int, int] = (CARD_W, CARD_H)) -> Image.Image:
    """RGBA card background: the jacket art, strongest at the left (behind the jacket) and fading out
    to the right. A card wider than a B50 card has it on its right instead, fading out to the left."""
    w, h = size
    if mode == "light":
        return Image.new("RGBA", (w, h), (255, 255, 255, 236))
    base = Image.new("RGBA", (w, h), (*fallback, 228))
    if mode == "flat":
        return Image.new("RGBA", (w, h), (*fallback, 235))
    if not path:
        return base
    aw = min(w, CARD_W)  # a wide card shows the art on its right part only, not blown up
    try:
        with Image.open(path) as im:
            art = ImageOps.fit(im.convert("RGB"), (aw, aw), Image.LANCZOS)
    except Exception:
        return base
    art = art.crop((0, (aw - h) // 2, aw, (aw + h) // 2))
    art = Image.blend(art, Image.new("RGB", art.size, (12, 12, 20)), 0.35).convert("RGBA")
    fade = Image.linear_gradient("L").rotate(90).resize((aw, h))  # 0 at left -> 255 at right
    fade = fade.point(lambda v: 255 - v)  # 255 at left -> 0 at right
    fade = fade.point(lambda v: int(min(255, max(0, (v - 40) * 1.3))))
    if w > aw:
        fade = ImageOps.mirror(fade)
    art.putalpha(fade)
    base.alpha_composite(art, (w - aw, 0))
    return base


# ------------------------------------------------------------------- card


def _spaced_text(draw: ImageDraw.ImageDraw, center: tuple[float, float], text: str, font, fill, gap: float) -> None:
    """Letters placed so the gaps between their inked shapes are all `gap` (a space: a wider gap),
    which keeps round letters like O from looking crammed next to their neighbours."""
    boxes = [None if c == " " else font.getbbox(c) for c in text]
    widths = [b[2] - b[0] if b else 0 for b in boxes]
    steps = [gap * 5 if c == " " else gap for c in text[1:]]
    x = center[0] - (sum(widths) + sum(steps) - (gap if " " in text else 0)) / 2
    for c, b, w in zip(text, boxes, widths):
        if b is None:
            x += gap * 4
            continue
        draw.text((x - b[0], center[1]), c, font=font, fill=fill, anchor="lm")
        x += w + gap


# the WORLD'S END colors, a little brighter so text in them reads on dark cards
WE_GRADIENT = [(50, 140, 255), (90, 200, 90), (245, 195, 20), (240, 70, 45), (235, 45, 165)]


def _rainbow_text(text: str, font, outline: bool = False, pad: int = 3) -> Image.Image:
    """`text` in a left-to-right gradient through the WORLD'S END colors (with a thin dark
    outline for light backgrounds)."""
    stroke = 1 if outline else 0
    bb = font.getbbox(text, stroke_width=stroke)
    w, h = bb[2] - bb[0] + pad * 2, bb[3] - bb[1] + pad * 2
    at = (pad - bb[0], pad - bb[1])
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if outline:
        ImageDraw.Draw(out).text(at, text, font=font, fill=(*WE_OUTLINE, 255), stroke_width=1,
                                 stroke_fill=(*WE_OUTLINE, 255))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text(at, text, font=font, fill=255)
    ink = mask.getbbox() or (0, 0, w, h)  # spread the colors over the letters, not the padding
    fill = Image.new("RGB", (w, h))
    fill.paste(_horizontal_gradient((ink[2] - ink[0], h), WE_GRADIENT), (ink[0], 0))
    out.paste(fill, (0, 0), mask)
    return out


def _we_attribute(level: str) -> tuple[str, int] | None:
    """("狂", 5) from a WORLD'S END level like "狂☆5"."""
    m = re.match(r"^(.)☆(\d)$", level or "")
    return (m.group(1), int(m.group(2))) if m else None


def _star(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    """A five-pointed star (drawn, so every one is the same size and shape)."""
    import math

    pts = []
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        rr = r if k % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    draw.polygon(pts, fill=fill)


@lru_cache(maxsize=16)
def _we_badge(kanji: str, stars: int, size: int) -> Image.Image:
    """The in-game WORLD'S END attribute tile: a white tile, a dark bar with the lit gold stars
    centred on it, and the attribute kanji in the rainbow under it. `size` is its width; it is a bit
    taller than wide. Drawn at 4x and shrunk, so the small stars come out smooth."""
    ss = 4
    w, h = size * ss, round(size * 1.18) * ss
    bar = max(8 * ss, round(h * 0.24))
    body = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(body)
    draw.rectangle((0, 0, w, bar), fill=(22, 50, 66))
    r = bar * 0.38
    step = min(r * 2.15, (w - 2 * ss) / max(1, stars))
    x0 = (w - step * (stars - 1)) / 2
    for i in range(stars):
        _star(draw, x0 + step * i, bar / 2 + ss / 2, r, (255, 208, 64))
    k = _rainbow_text(kanji, cjk(round((h - bar) * 0.8)))
    body.alpha_composite(k, ((w - k.width) // 2, bar + (h - bar - k.height) // 2 + ss))
    body.putalpha(_rounded_mask((w, h), max(3, size // 12) * ss))
    body = body.resize((size, round(size * 1.18)), Image.LANCZOS)

    bw, bh = body.size
    tile = Image.new("RGBA", (bw + 4, bh + 6), (0, 0, 0, 0))
    shadow = Image.new("L", tile.size, 0)
    ImageDraw.Draw(shadow).rounded_rectangle((2, 4, bw + 1, bh + 3), radius=max(3, size // 12), fill=110)
    tile.putalpha(shadow.filter(ImageFilter.GaussianBlur(2)))
    tile.alpha_composite(body, (2, 1))
    return tile


UTAGE_PINK, UTAGE_DEEP = (236, 60, 214), (150, 10, 130)  # maimai DX NET's U·TA·GE label


def _utage_title(title: str) -> tuple[str | None, str]:
    """("協", "Love You") from a 宴 title like "[協]Love You"."""
    m = re.match(r"^\[(.)\](.*)$", title or "")
    return (m.group(1), m.group(2).strip()) if m else (None, title)


def _maimai_label(text: str, font, color: tuple[int, int, int], deep: tuple[int, int, int]) -> Image.Image:
    """Text like maimai's difficulty labels: white letters, a thick colored outline and a darker
    drop under them."""
    stroke = max(2, font.size // 7)
    bb = font.getbbox(text, stroke_width=stroke)
    w, h = bb[2] - bb[0] + 4, bb[3] - bb[1] + 4 + stroke
    at = (2 - bb[0], 2 - bb[1])
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(out)
    draw.text((at[0], at[1] + stroke), text, font=font, fill=deep, stroke_width=stroke, stroke_fill=deep)
    draw.text(at, text, font=font, fill=WHITE, stroke_width=stroke, stroke_fill=color)
    return out


def _draw_card(canvas: Image.Image, x: int, y: int, idx: int, e: Entry, theme: dict, st: dict,
               title_reserve: int = 0) -> None:
    """One chart card. title_reserve: room kept free at the right of the title row (drops the #n)."""
    label, color, is_dx = _diff(e)
    mask = _rounded_mask((CARD_W, CARD_H), RADIUS)
    if st["card"] == "light":
        shadow = Image.new("RGBA", (CARD_W + 24, CARD_H + 24), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((12, 16, CARD_W + 11, CARD_H + 15), radius=RADIUS,
                                                 fill=(60, 40, 90, 40))
        shadow = shadow.filter(ImageFilter.GaussianBlur(7))
        _over(canvas, shadow, (x - 12, y - 12))
    bg = _card_background(e.jacket_path, st["card"], theme["card"])
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    card.paste(bg, (0, 0), mask)
    _over(canvas, card, (x, y))
    draw = ImageDraw.Draw(canvas)

    # jacket with a difficulty-colored frame and a level tag along the bottom
    jx, jy = x + 12, y + 12
    ultima = label == "ULT"
    worlds_end = label == "WE"
    if ultima:  # in-game ULTIMA: black with a red rim
        draw.rounded_rectangle((jx - 5, jy - 5, jx + JACKET + 4, jy + JACKET + 4), radius=11, fill=(210, 20, 50))
        draw.rounded_rectangle((jx - 3, jy - 3, jx + JACKET + 2, jy + JACKET + 2), radius=9, fill=(12, 12, 14))
    elif worlds_end:  # white, so the rainbow label below stands out
        draw.rounded_rectangle((jx - 3, jy - 3, jx + JACKET + 2, jy + JACKET + 2), radius=9, fill=(245, 245, 248))
    else:
        draw.rounded_rectangle((jx - 3, jy - 3, jx + JACKET + 2, jy + JACKET + 2), radius=9, fill=color)
    jacket = _load_jacket(e.jacket_path) if e.jacket_path else None
    if jacket is None:
        jacket = Image.new("RGB", (JACKET, JACKET), (24, 24, 32))
        ImageDraw.Draw(jacket).text((JACKET // 2, JACKET // 2 - 8), "NO IMAGE", font=num(16, "SemiBold"),
                                    fill=FAINT, anchor="mm")
    canvas.paste(jacket, (jx, jy), _rounded_mask((JACKET, JACKET), 7))
    tag_h = 24
    const = f"{e.level_const:.1f}" if e.level_const else e.level
    tag_font = lambda t: num(17) if t.isascii() else cjk(15)  # noqa: E731  (宴, WORLD'S END's 狂☆5)
    if worlds_end:  # like CHUNITHM-NET's WORLD'S END label: cream, evenly spaced letters with a hard shadow
        tag = _we_texture(JACKET, tag_h)
        td = ImageDraw.Draw(tag)
        _spaced_text(td, (JACKET / 2 + 1, tag_h / 2 + 1), "WORLD'S END", num(18), WE_OUTLINE, 1.6)
        _spaced_text(td, (JACKET / 2, tag_h / 2), "WORLD'S END", num(18), WE_TEXT, 1.6)
        canvas.paste(tag, (jx, jy + JACKET - tag_h))
        # the attribute tile at the jacket's top right, as in the game
        attr = _we_attribute(const)
        if attr:
            tile = _we_badge(*attr, 30)
            _over(canvas, tile, (jx + JACKET - tile.width - 2, jy + 2))
            draw = ImageDraw.Draw(canvas)
    else:
        draw.rectangle((jx, jy + JACKET - tag_h, jx + JACKET - 1, jy + JACKET - 1),
                       fill=(12, 12, 14) if ultima else color)
        # light tags (Re:MASTER) need dark text; ULTIMA uses red on black
        tag_text = (255, 60, 80) if ultima else (60, 24, 96) if sum(color) > 560 else WHITE
        draw.text((jx + 6, jy + JACKET - tag_h / 2), label, font=tag_font(label), fill=tag_text, anchor="lm")
        draw.text((jx + JACKET - 6, jy + JACKET - tag_h / 2), const, font=tag_font(const), fill=tag_text, anchor="rm")
    if is_dx:
        draw.rounded_rectangle((jx + 4, jy + 4, jx + 30, jy + 20), radius=4, fill=(255, 255, 255))
        draw.text((jx + 17, jy + 12), "DX", font=num(14), fill=(230, 70, 110), anchor="mm")

    # text column
    tx = jx + JACKET + 16
    right = x + CARD_W - 14
    if title_reserve:
        title_w = right - tx - title_reserve - 8
    else:
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


def _rating_number(game: str, rating: str, font) -> Image.Image:
    """The rating in its tier's colors, shaded top to bottom like the official sites' digits."""
    return _gradient_text(rating, font, _plate_colors(game, rating), vertical=True)


def _stat(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, value: str, st: dict) -> int:
    draw.text((x, y), label, font=num(16, "SemiBold"), fill=st["faint"])
    draw.text((x, y + 20), value, font=num(30), fill=st["text"])
    return int(x + max(draw.textlength(label, font=num(16, "SemiBold")), draw.textlength(value, font=num(30)))) + 36


LOGO_BOX = (520, 216)  # logo area, centered at the top
LOGO_GRADIENTS = {
    "maimai": [(255, 120, 190), (255, 196, 90), (110, 214, 255)],
    "chunithm": [(255, 226, 90), (255, 150, 60), (240, 70, 120)],
}


def _gradient_text(text: str, font, stops, vertical: bool = False) -> Image.Image:
    """Text filled with a gradient (left to right, or top to bottom over the letters), with a soft shadow."""
    l, t, r, b = font.getbbox(text)
    w, h = r - l + 16, b - t + 16
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((8 - l, 8 - t), text, font=font, fill=255)
    if vertical:
        fill = Image.new("RGB", (w, h), stops[0])
        fill.paste(_horizontal_gradient((h - 16, w), stops).transpose(Image.Transpose.ROTATE_270), (0, 8))
        fill.paste(Image.new("RGB", (w, 8), stops[-1]), (0, h - 8))
        fill = fill.convert("RGBA")
    else:
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
    room = width - 2 * (MARGIN + 560 + 20)  # between the player plate and the rating plate
    if logo.width > room:
        logo = logo.resize((room, round(logo.height * room / logo.width)), Image.LANCZOS)
    _over(canvas, logo, ((width - logo.width) // 2, 10 + (LOGO_BOX[1] - logo.height) // 2))


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


def _draw_player(canvas: Image.Image, name: str, icon: bytes | None, kicker: str, stats: list[tuple[str, str]],
                 max_right: int, theme: dict, st: dict) -> None:
    """The player at the top left without a plate, like the play log: icon, kicker and name, and a
    line of stats (label, value) under them."""
    cx, cy, size = MARGIN, 44, 116
    tx = cx
    ic = _open_image(icon)
    if ic is not None:
        ic = ImageOps.fit(ic, (size, size), Image.LANCZOS)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(ic, (0, 0), _rounded_mask((size, size), 22))
        _over(canvas, out, (cx, cy))
        tx = cx + size + 26
    draw = ImageDraw.Draw(canvas)
    name = unicodedata.normalize("NFKC", name)  # official sites use full-width letters
    draw.text((tx, cy + 26), kicker, font=num(26, "SemiBold"), fill=theme["accent"], anchor="ls")
    draw.text((tx - 2, cy + 104), _fit(draw, name, cjk(60), max_right - tx), font=cjk(60), fill=WHITE, anchor="ls")

    sx, base = cx + 2, cy + size + 46
    for label, value in stats:
        draw.text((sx, base), label, font=num(20, "SemiBold"), fill=st["muted"], anchor="ls")
        sx += draw.textlength(label, font=num(20, "SemiBold")) + 10
        draw.text((sx, base), value, font=num(30), fill=WHITE, anchor="ls")
        sx += draw.textlength(value, font=num(30)) + 36


def _draw_header(canvas: Image.Image, b50: B50, width: int, theme: dict, st: dict) -> None:
    old_slots, new_slots = SLOTS[b50.game]
    _draw_logo(canvas, b50.game, width, theme)

    # CHUNITHM's rating is an average, so the two averages; maimai's is a sum, so the two sums
    if b50.game == "chunithm":
        stats = [(f"BEST {old_slots} AVG", b50.average_text(b50.old)),
                 (f"NEW {new_slots} AVG", b50.average_text(b50.new))]
    else:
        stats = [(f"BEST {old_slots}", str(int(b50.old_sum))), (f"NEW {new_slots}", str(int(b50.new_sum)))]
    logo_left = (width - min(_logo_image(b50.game).width, width - 2 * (MARGIN + 580))) // 2
    _draw_player(canvas, b50.username, b50.icon, f"{GAME_NAMES[b50.game].upper()}  PLAYER", stats,
                 logo_left - 24, theme, st)

    # the rating at the top right, just the number in its tier's colors
    rating = b50.official_rating or b50.total_text()
    right = width - MARGIN
    number = _rating_number(b50.game, rating, num(120))
    _over(canvas, number, (right - number.width + 12, 52))
    if b50.official_rating and b50.official_rating != b50.total_text():
        ImageDraw.Draw(canvas).text((right, 176), f"CALCULATED {b50.total_text()}", font=num(18, "SemiBold"),
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
            _over(canvas, glow, (px - 20, py - 20))
        panel = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        border = _gradient_fill((pw, ph), colors)
        border.putalpha(_rounded_mask((pw, ph), 20))
        panel.alpha_composite(border)
        inner = Image.new("RGBA", (pw - 6, ph - 6), (14, 12, 24, 225))
        inner.putalpha(_rounded_mask((pw - 6, ph - 6), 17).point(lambda v: v * 225 // 255))
        panel.alpha_composite(inner, (3, 3))
        _over(canvas, panel, (px, py))
        draw.text((px + 22, py + 18), "RATING", font=num(18, "SemiBold"), fill=st["muted"])
        if tier.startswith("極"):
            label = _gradient_text("極 RAINBOW", cjk(18), [tuple(min(255, c + 40) for c in col) for col in colors])
            _over(canvas, label, (px + pw - 14 - label.width, py + 10))
        else:
            draw.text((px + pw - 22, py + 18), tier, font=num(18, "SemiBold"), fill=st["muted"], anchor="ra")
        number = _rating_number(game, rating, num(84))
        _over(canvas, number, (px + pw - 18 - number.width, py + ph - 14 - number.height))

    elif PLATE_STYLE == "bare":
        # no panel: large gradient number with a thin tier bar under it
        number = _rating_number(game, rating, num(104))
        nx, ny = right - number.width + 8, 62
        _over(canvas, number, (nx, ny))
        draw.text((right, 34), f"RATING  ·  {tier}", font=num(18, "SemiBold"), fill=st["muted"], anchor="ra")
        bar = _gradient_fill((number.width - 16, 5), colors)
        bar.putalpha(_rounded_mask(bar.size, 2))
        _over(canvas, bar, (right - bar.width, ny + number.height + 2))

    else:  # "stripe": dark panel with a tier-colored stripe on the left, white number
        pw, ph = 340, 132
        px, py = right - pw, 42
        panel = Image.new("RGBA", (pw, ph), (12, 10, 22, 215))
        stripe = _gradient_fill((14, ph), list(reversed(colors)))
        panel.paste(stripe, (0, 0))
        mask = _rounded_mask((pw, ph), 16)
        out = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        out.paste(panel, (0, 0), mask)
        _over(canvas, out, (px, py))
        draw.text((px + 32, py + 18), "RATING", font=num(18, "SemiBold"), fill=st["muted"])
        tier_img = _gradient_text(tier, num(18, "SemiBold"), [tuple(min(255, c + 40) for c in col) for col in colors])
        _over(canvas, tier_img, (px + pw - 12 - tier_img.width, py + 10))
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


# finished "version" backgrounds, saved once per game and size: making one decodes, blurs and
# scales the key art (+14MB for a moment on a small host), opening the saved one costs just the image
BG_CACHE_DIR = Path(os.environ.get("CACHE_DIR", "data/cache"))


def _background(b50: B50, size: tuple[int, int], theme: dict, st: dict) -> Image.Image:
    if st["bg"] != "version":
        return _make_background(b50, size, theme, st)
    art = next((ASSETS / "backgrounds" / f"{b50.game}.{e}" for e in ("webp", "png", "jpg")
                if (ASSETS / "backgrounds" / f"{b50.game}.{e}").is_file()), None)
    stamp = int(art.stat().st_mtime) if art else 0
    path = BG_CACHE_DIR / f"bg_{b50.game}_{size[0]}x{size[1]}_{stamp}.png"
    try:
        with Image.open(path) as im:
            im.load()
            return im.copy() if im.mode in ("RGB", "RGBA") else im.convert("RGB")
    except (OSError, ValueError):
        pass
    bg = _make_background(b50, size, theme, st)
    try:
        BG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for old in BG_CACHE_DIR.glob(f"bg_{b50.game}_{size[0]}x{size[1]}_*.png"):
            old.unlink(missing_ok=True)  # an older key art's
        bg.save(path, compress_level=3)
    except OSError:
        pass
    return bg


def _make_background(b50: B50, size: tuple[int, int], theme: dict, st: dict) -> Image.Image:
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
                # The art is blurred and darkened, so do that at half size (still larger than the
                # source image, so nothing is lost) and enlarge once: a third of the memory.
                k = 0.5 if w * 0.5 >= src.width else 1.0
                if src.width / src.height > w / h:
                    # wide key art: fit to the width at the top and fade it out downward
                    ah = round(src.height * w / src.width)
                    sw, sh = round(w * k), round(ah * k)
                    art = src.resize((sw, sh), Image.LANCZOS)
                    blur = 2 if w / src.width < 2.5 else w / src.width
                    art = art.filter(ImageFilter.GaussianBlur(blur * k))
                    art = Image.blend(art, Image.new("RGB", art.size, theme["bottom"]), dark)
                    fade = Image.linear_gradient("L").resize((sw, sh)).point(lambda v: 255 - max(0, v - 128) * 2)
                    base = _vertical_gradient(size, theme["top"], theme["bottom"])
                    # paste through the fade mask: blends in place, no full-size RGBA copy
                    base.paste(art.resize((w, ah), Image.BILINEAR), (0, 0), fade.resize((w, ah), Image.BILINEAR))
                    return base
                # small images get blurred more (hides upscaling artifacts), bright ones darkened more
                scale = max(w / src.width, h / src.height)
                small = (round(w * k), round(h * k))
                art = ImageOps.fit(src, small, Image.LANCZOS, centering=(0.5, 0.0))
                art = art.filter(ImageFilter.GaussianBlur((3 if scale < 2.5 else scale * 2) * k))
                art = Image.blend(art, Image.new("RGB", small, theme["bottom"]), dark).convert("RGBA")
                shade = Image.new("RGBA", small, (*theme["bottom"], 0))
                shade.putalpha(Image.linear_gradient("L").resize(small).point(lambda v: v * 120 // 255))
                art.alpha_composite(shade)
                return art.convert("RGB").resize(size, Image.BILINEAR)

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


def render_b50(b50: B50, now: datetime | None = None, style: str | None = None, scale: float | None = None) -> bytes:
    """The B50 page. scale < 1 (low-memory mode) makes a smaller image: the page is drawn a strip
    at a time at full size and each strip is shrunk into the small page, so only the small page
    and one strip are in memory, and the layout code stays the same."""
    theme = THEMES[b50.game]
    st = STYLES[style or os.environ.get("B50_STYLE", DEFAULT_STYLE)]
    scale = B50_SCALE if scale is None else scale
    old_slots, new_slots = SLOTS[b50.game]
    old_rows, new_rows = -(-old_slots // COLS), -(-new_slots // COLS)
    width = MARGIN * 2 + COLS * CARD_W + (COLS - 1) * GAP_X
    height = (HEADER_H + 2 * SECTION_H + (old_rows + new_rows) * (CARD_H + GAP_Y) + FOOTER_H)

    # (top, bottom, draw(canvas, dy)): everything drawn inside [top, bottom), shifted by dy
    strips = [(0, HEADER_H, lambda c, dy: _draw_header(c, b50, width, theme, st))]
    y = HEADER_H
    for title, sub, entries, rows in (
        (f"BEST {old_slots}", "OLD VERSIONS", b50.old, old_rows),
        (f"NEW {new_slots}", "CURRENT VERSION", b50.new, new_rows),
    ):
        strips.append((y, y + SECTION_H,
                       lambda c, dy, y=y, t=title, s=sub: _draw_section(c, y + dy, t, s, width, theme, st)))
        y += SECTION_H
        for r in range(rows):
            ry = y + r * (CARD_H + GAP_Y)

            def row(c, dy, ry=ry, first=r * COLS, entries=entries):
                for i, e in enumerate(entries[first:first + COLS], start=first):
                    _draw_card(c, MARGIN + (i % COLS) * (CARD_W + GAP_X), ry + dy, i + 1, e, theme, st)

            strips.append((ry, ry + CARD_H + GAP_Y, row))
        y += rows * (CARD_H + GAP_Y)

    def footer(c, dy):
        stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
        source = f"{b50.source}  ·  " if b50.source else ""
        ImageDraw.Draw(c).text((width - MARGIN, height - 28 + dy), f"{source}{stamp}", font=num(17, "Medium"),
                               fill=st["faint"], anchor="rm")

    strips.append((height - FOOTER_H, height, footer))

    return _paint(strips, (width, height), lambda size: _rgb(_background(b50, size, theme, st)), scale)


def _paint(strips, size: tuple[int, int], background, scale: float) -> bytes:
    """Draw a page from strips (top, bottom, draw(canvas, dy)) and encode it.

    At scale < 1 each strip is drawn at full size over the enlarged background and shrunk into
    a small page, so memory holds the small page and one strip instead of the full page.
    """
    width, height = size
    if scale >= 1:
        canvas = background(size)
        for _, _, draw in strips:
            draw(canvas, 0)
        return encode(canvas)
    sw, sh = round(width * scale), round(height * scale)
    page = background((sw, sh))
    for top, bottom, draw in strips:
        sy0, sy1 = round(top * scale), round(bottom * scale)
        if sy1 <= sy0:
            continue
        strip = page.crop((0, sy0, sw, sy1)).resize((width, bottom - top), Image.BICUBIC)
        draw(strip, -top)
        page.paste(strip.resize((sw, sy1 - sy0), Image.LANCZOS), (0, sy0))
        strip.close()
    return encode(page)


# ------------------------------------------------------------ play log card

def _play_badge_style(game: str, badge):
    """(text, gradient colors or None, text color) for a play badge."""
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
    return text, colors, fg


def _play_badge_width(game: str, badge) -> int:
    text = _play_badge_style(game, badge)[0]
    return int(ImageDraw.Draw(Image.new("L", (1, 1))).textlength(text, font=num(15))) + 18


def _draw_play_badge(canvas: Image.Image, right: int, y: int, game: str, badge) -> int:
    """NEW (+improvement) / TIE / BEST <score>, right-aligned at `right`. Returns its left edge."""
    text, colors, fg = _play_badge_style(game, badge)
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
    _over(canvas, pill, (bx, y))
    ImageDraw.Draw(canvas).text((bx + bw // 2, y + bh // 2), text, font=f, fill=fg, anchor="mm")
    return bx


def _draw_count_pill(canvas: Image.Image, right: int, y: int, count: int, size: int = 26) -> int:
    """"×N" (played N times) in a bright pill, right-aligned at `right`. Returns its left edge."""
    text, f = f"×{count}", num(size)
    bw, bh = int(ImageDraw.Draw(canvas).textlength(text, font=f)) + size * 16 // 26, size * 32 // 26
    pill = _gradient_fill((bw, bh), [(255, 236, 120), (255, 170, 60)])
    pill.putalpha(_rounded_mask((bw, bh), 10))
    ImageDraw.Draw(pill).rounded_rectangle((0, 0, bw - 1, bh - 1), radius=10, outline=(40, 24, 10), width=2)
    _over(canvas, pill, (right - bw, y))
    ImageDraw.Draw(canvas).text((right - bw // 2, y + bh // 2 + 1), text, font=f, fill=(40, 24, 10), anchor="mm")
    return right - bw


RISE = (90, 220, 140)  # rating went up


def _rating_change(game: str, before: str | None, after: str | None) -> str | None:
    """"+0.02" / "+35" when the rating went up, else None."""
    try:
        diff = float(after) - float(before)
    except (TypeError, ValueError):
        return None
    if diff <= 0:
        return None
    return f"+{diff:.2f}" if game == "chunithm" else f"+{round(diff)}"


def _up_pill(canvas: Image.Image, right: int, y: int, text: str, size: int) -> int:
    """Green "▲ +0.012" pill, right-aligned at `right`. Returns its left edge."""
    draw = ImageDraw.Draw(canvas)
    f = num(size)
    h = size + 6
    tri = h // 2 - 1
    w = int(draw.textlength(text, font=f)) + tri + 22
    x = right - w
    _panel(canvas, (x, y, right, y + h), (20, 70, 45), alpha=220, radius=h // 2, outline=False)
    draw = ImageDraw.Draw(canvas)
    cx, cy = x + 9, y + h / 2
    draw.polygon([(cx, cy + tri / 2), (cx + tri, cy + tri / 2), (cx + tri / 2, cy - tri / 2)], fill=RISE)
    draw.text((cx + tri + 5, cy), text, font=f, fill=RISE, anchor="lm")
    return x


PLAY_ROW_H = 128  # one track of a credit
CREDIT_HEADER_H = 128
CREDIT_LOGO = (190, 100)  # logo box in the play log header


def _draw_play_row(canvas: Image.Image, x: int, y: int, w: int, idx: int, e: Entry, badge, game: str,
                   theme: dict, st: dict) -> None:
    """A track as a wide row: number, jacket, title, difficulty, score, rank and lamp; the badge,
    the rating gain and the song rating on the right."""
    h = PLAY_ROW_H
    # like the B50 cards: the jacket art shows on the right, fading out to the left
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    card.paste(_card_background(e.jacket_path, st["card"], theme["card"], (w, h)), (0, 0), _rounded_mask((w, h), RADIUS))
    ImageDraw.Draw(card).rounded_rectangle((0, 0, w - 1, h - 1), radius=RADIUS, outline=(255, 255, 255, 40), width=2)
    _over(canvas, card, (x, y))
    draw = ImageDraw.Draw(canvas)
    draw.text((x + 26, y + h / 2), str(idx), font=num(40), fill=(120, 122, 150), anchor="mm")
    js = h - 24
    _framed_jacket(canvas, x + 52, y + 12, js, e.jacket_path, e.difficulty)
    draw = ImageDraw.Draw(canvas)
    tx, right = x + 52 + js + 22, x + w - 20

    # right side: badge on top, the rating gain under it, the song rating at the bottom
    rating_text = e.rating_text
    maxed = e.rated and e.score >= (100.5 if game == "maimai" else 1_009_000)
    draw.text((right, y + h - 16), rating_text, font=num(46), fill=MAX_RATING if maxed else st["text"], anchor="rs")
    side = int(draw.textlength(rating_text, font=num(46)))
    if badge is not None:
        side = max(side, right - _draw_play_badge(canvas, right, y + 14, game, badge))
        if badge.gain:
            gain = f"+{float(badge.gain):.3f}" if game == "chunithm" else f"+{int(badge.gain)}"
            _up_pill(canvas, right, y + 44, gain, 15)
        draw = ImageDraw.Draw(canvas)

    label, name, color, _ = _diff_info(e.difficulty)
    kanji = _utage_title(e.title)[0] if label == "宴" else None  # the title keeps its [協]
    draw.text((tx, y + 14), _fit(draw, e.title, cjk(24), right - side - 24 - tx), font=cjk(24), fill=st["text"])
    level = f"{e.level_const:.1f}" if e.level_const else e.level  # just the constant (unrated charts: their level)
    if label == "WE":  # WORLD'S END in the label's rainbow; the attribute tile on the jacket, as in the game
        info_font = num(21, "SemiBold")  # the same font and baseline as the other difficulties
        top = info_font.getbbox(name, anchor="ls")
        _over(canvas, _rainbow_text(name, info_font), (tx + top[0] - 3, y + 70 + top[1] - 3))
        attr = _we_attribute(level)
        if attr:
            tile = _we_badge(*attr, 38)
            _over(canvas, tile, (x + 40, y + h - tile.height + 2))
        draw = ImageDraw.Draw(canvas)
    elif label == "宴":  # the U·TA·GE label as on maimai DX NET, the kanji tile on the jacket as in the game
        tag = _maimai_label("U·TA·GE", num(22), UTAGE_PINK, UTAGE_DEEP)
        _over(canvas, tag, (tx - 2, y + 48))
        lv = _maimai_label(level, num(22), UTAGE_PINK, UTAGE_DEEP)
        _over(canvas, lv, (tx - 2 + tag.width + 8, y + 48))
        if kanji:  # the kanji alone over the jacket's bottom left, lettered like the U·TA·GE label
            mark = _maimai_label(kanji, cjk(30), UTAGE_PINK, UTAGE_DEEP)
            _over(canvas, mark, (x + 42, y + h - mark.height - 4))
        draw = ImageDraw.Draw(canvas)
    else:
        info_font = num(21, "SemiBold") if level.isascii() else cjk(18)
        draw.text((tx, y + 70), f"{name}  {level}", font=info_font,
                  fill=tuple(min(255, v + 50) for v in color), anchor="ls")

    score = e.score_text
    draw.text((tx, y + h - 14), score, font=num(40), fill=st["text"], anchor="ls")
    sx = tx + draw.textlength(score, font=num(40)) + 16
    draw.text((sx, y + h - 18), e.rank, font=num(24), fill=st["rank"] if e.rank in RANK_COLORS else st["muted"],
              anchor="ls")
    if e.lamp:  # a box around AJC/AJ/FC, centred on the rank's letters
        rb = num(24).getbbox(e.rank or "S", anchor="ls")
        mid = y + h - 18 + (rb[1] + rb[3]) / 2
        lx = sx + draw.textlength(e.rank, font=num(24)) + 10
        lw = draw.textlength(e.lamp, font=num(16)) + 12
        lamp_color = LAMP_COLORS.get(e.lamp, st["muted"])
        draw.rounded_rectangle((lx, mid - 11, lx + lw, mid + 11), radius=5, outline=lamp_color, width=2)
        draw.text((lx + lw / 2, mid), e.lamp, font=num(16), fill=lamp_color, anchor="mm")


def render_credit(game: str, player: str, entries: list[Entry], badges: list, date: str,
                  icon: bytes | None = None, rating: str | None = None, rating_before: str | None = None) -> bytes:
    """One credit: the player, logo and rating on top, then a wide row per track.

    badges: a playlog.Badge (or None) per entry.
    """
    from types import SimpleNamespace

    theme = THEMES[game]
    st = STYLES["version"]
    width = MARGIN * 2 + 2 * CARD_W + GAP_X  # as wide as the old 2x2 play log, so it isn't a long strip
    header = CREDIT_HEADER_H
    height = header + len(entries) * (PLAY_ROW_H + GAP_Y) + 26
    # Discord fits images into one box, so a taller credit (4 tracks) would show narrower than a
    # 3-track one; keep at least the 3-track shape by making it wider instead
    three = header + 3 * (PLAY_ROW_H + GAP_Y) + 26
    width = max(width, round(height * width / three))
    stub = SimpleNamespace(game=game, old=entries, new=[], icon=icon)
    canvas = _rgb(_background(stub, (width, height), theme, st))
    _draw_play_header(canvas, game, player, icon, f"PLAY LOG  ·  {date}", rating, rating_before, width, theme, st)
    if len(entries) >= 4:  # the extra track bought with C to C, under the rating
        ImageDraw.Draw(canvas).text((width - MARGIN, 104), "C to C", font=num(17, "SemiBold"), fill=theme["accent"],
                                    anchor="ra")

    for i, e in enumerate(entries):
        _draw_play_row(canvas, MARGIN, header + i * (PLAY_ROW_H + GAP_Y), width - 2 * MARGIN, i + 1, e,
                       badges[i] if i < len(badges) else None, game, theme, st)
    return encode(canvas)


def _draw_play_header(canvas: Image.Image, game: str, player: str, icon: bytes | None, kicker: str,
                      rating: str | None, rating_before: str | None, width: int, theme: dict, st: dict) -> None:
    """The play log's top: icon, kicker and name at the left, the logo, and the rating at the right."""
    x = MARGIN
    ic = _open_image(icon)
    if ic is not None:
        ic = ImageOps.fit(ic, (72, 72), Image.LANCZOS)
        out = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
        out.paste(ic, (0, 0), _rounded_mask((72, 72), 14))
        _over(canvas, out, (x, 30))
        x += 90
    logo = _logo_image(game).copy()
    logo.thumbnail(CREDIT_LOGO, Image.LANCZOS)
    logo_x = (width - logo.width) // 2
    _over(canvas, logo, (logo_x, 10 + (CREDIT_LOGO[1] - logo.height) // 2))
    draw = ImageDraw.Draw(canvas)
    draw.text((x, 30), kicker, font=num(18, "SemiBold"), fill=theme["accent"])
    name = unicodedata.normalize("NFKC", player)
    draw.text((x, 52), _fit(draw, name, cjk(38), logo_x - x - 16), font=cjk(38), fill=WHITE)

    # rating at the top right: the number in its tier colors, where it came from, and the gain
    if rating:
        draw = ImageDraw.Draw(canvas)
        right = width - MARGIN
        colors = _plate_colors(game, rating)
        number = _rating_number(game, rating, num(62))
        _over(canvas, number, (right - number.width + 8, 44))
        change = _rating_change(game, rating_before, rating)
        draw = ImageDraw.Draw(canvas)
        draw.text((right, 24), f"RATING   {rating_before} »" if change else "RATING", font=num(16, "SemiBold"),
                  fill=st["muted"], anchor="ra")
        if change:
            _up_pill(canvas, right - number.width - 2, 68, change, 18)


@dataclass
class DaySlot:
    """A chart in /today's timeline: played `count` times in a row, `entry` the best of them."""

    entry: Entry
    new: bool  # any of them a new record
    count: int = 1


@dataclass
class DayCredit:
    time: str  # "18:00"
    slots: list[DaySlot]


DAY_MIN_COL, DAY_MAX_COL = 132, 210  # a credit's column
DAY_MAX_W = 2600
DAY_GRAPH_H = 230


def _day_rating_graph(canvas: Image.Image, box: tuple[int, int, int, int], steps: list[tuple[float, float]],
                      start: float, game: str, theme: dict, st: dict) -> None:
    """The rating over the day as a glowing line in `box`: flat, then a step up at each x in
    `steps` (x, gain), each labelled; the value at both ends. Only the box's area is drawn on
    layers, so it stays light on memory."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    acc = theme["accent"]
    end = start + sum(g for _, g in steps)
    span = max(end - start, 0.02 if game == "chunithm" else 20)
    lo, hi = start - span * 0.12, start + span * 1.25  # room above for the labels

    def y_of(v: float) -> float:
        return h - (v - lo) / (hi - lo) * h

    pts, cur = [(0.0, y_of(start))], start
    for x, g in steps:
        pts.append((x - x0, y_of(cur)))
        cur += g
        pts.append((x - x0, y_of(cur)))
    pts.append((float(w), y_of(cur)))

    region = canvas.crop((x0, y0, x1, y1)).convert("RGBA")
    # the area under the line, fading downward
    area = Image.new("L", (w, h), 0)
    ImageDraw.Draw(area).polygon(pts + [(w, h), (0, h)], fill=255)
    fade = Image.linear_gradient("L").resize((w, h)).point(lambda v: int(80 - v * 0.3))
    area = ImageChops.multiply(area, fade)
    region.paste(Image.new("RGBA", (w, h), (*acc, 255)), (0, 0), area)
    for v in (start, end):  # dashed guides at the day's start and end
        yy = y_of(v)
        d = ImageDraw.Draw(region)
        for x in range(0, w, 14):
            d.line((x, yy, x + 6, yy), fill=(*st["faint"], 160), width=1)
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).line(pts, fill=(*acc, 255), width=10, joint="curve")
    glow = glow.filter(ImageFilter.GaussianBlur(9))
    region.alpha_composite(glow)
    d = ImageDraw.Draw(region)
    d.line(pts, fill=(255, 244, 200), width=4, joint="curve")
    fmt = (lambda v: f"{v:.2f}") if game == "chunithm" else (lambda v: f"{v:.0f}")
    d.text((w - 2, y_of(end) + 30), fmt(end), font=num(24), fill=st["text"], anchor="rs")  # under the line
    if steps:
        d.text((4, y_of(start) - 10), fmt(start), font=num(22, "SemiBold"), fill=st["muted"], anchor="ls")
    last = -1e9
    cur = start
    for x, g in steps:
        cur += g
        px, py = x - x0, y_of(cur)
        d.ellipse((px - 7, py - 7, px + 7, py + 7), fill=(255, 244, 200), outline=acc, width=3)
        if px - last >= 64:  # skip a label that would sit on the one before
            text = f"+{g:.3f}" if game == "chunithm" else f"+{g:.0f}"
            d.text((px, py - 14), text, font=num(19), fill=acc, anchor="ms")
            last = px
    canvas.paste(region.convert("RGB"), (x0, y0))


def render_day(game: str, player: str, date: str, stats: list[tuple[str, str]], credits: list[DayCredit],
               steps: list[tuple[int, float, float]], rating_start: float | None, icon: bytes | None = None,
               rating: str | None = None, rating_before: str | None = None) -> bytes:
    """A day of play (/today) as a timeline: the play log's top, the day's numbers, the rating over
    the day (a step up at each new record that raised it), then a column per credit with its
    charts, new records lit up. `steps`: (credit, where in its column 0..1, rating gained);
    `rating_start`: the rating before the day's first play (None: no graph)."""
    from types import SimpleNamespace

    theme = THEMES[game]
    st = STYLES["version"]
    acc = theme["accent"]
    n = max(1, len(credits))
    col = max(DAY_MIN_COL, min(DAY_MAX_COL, (DAY_MAX_W - 2 * MARGIN) // n))
    width = max(2 * MARGIN + col * n, 1200)
    col = (width - 2 * MARGIN) / n  # a narrow day: the columns fill the width
    jacket = int(min(col, DAY_MAX_COL) - 26)
    slot_h = jacket + 62  # room for a stack of copies behind the next one
    depth = max((len(c.slots) for c in credits), default=0)
    stats_y = CREDIT_HEADER_H + 4
    graph_y = stats_y + 70
    graph = rating_start is not None
    lane_y = graph_y + (DAY_GRAPH_H + 40 if graph else 0)
    height = lane_y + 76 + depth * slot_h + 20

    stub = SimpleNamespace(game=game, old=[c.slots[0].entry for c in credits if c.slots], new=[], icon=icon)
    canvas = _rgb(_background(stub, (width, height), theme, st))
    _draw_play_header(canvas, game, player, icon, f"TODAY  ·  {date}", rating, rating_before, width, theme, st)
    draw = ImageDraw.Draw(canvas)
    x = MARGIN
    for label, value in stats:  # the day in numbers, in one line
        draw.text((x, stats_y + 44), value, font=num(40), fill=WHITE, anchor="ls")
        x += draw.textlength(value, font=num(40)) + 8
        draw.text((x, stats_y + 42), label, font=cjk(19), fill=st["muted"], anchor="ls")
        x += draw.textlength(label, font=cjk(19)) + 36
    if graph:
        points = [(MARGIN + col * (c + frac), gain) for c, frac, gain in steps]
        _day_rating_graph(canvas, (MARGIN, graph_y, width - MARGIN, graph_y + DAY_GRAPH_H), points, rating_start,
                          game, theme, st)

    for ci, credit in enumerate(credits):
        cx = MARGIN + col * ci
        draw = ImageDraw.Draw(canvas)
        draw.text((cx + col / 2, lane_y + 14), f"CREDIT {ci + 1}", font=num(18, "SemiBold"), fill=st["muted"],
                  anchor="ms")
        draw.text((cx + col / 2, lane_y + 40), credit.time, font=num(26), fill=st["text"], anchor="ms")
        if ci:
            for yy in range(lane_y, height - 24, 10):
                draw.line((cx, yy, cx, yy + 4), fill=st["faint"], width=1)
        y = lane_y + 76
        jx = int(cx + (col - jacket) / 2)
        for slot in credit.slots:
            e = slot.entry
            for k in range(min(slot.count - 1, 3), 0, -1):  # played again: copies stacked behind
                _framed_jacket(canvas, jx + k * 7, y - k * 7, jacket, e.jacket_path, e.difficulty)
                _over(canvas, Image.new("RGBA", (jacket, jacket), (8, 10, 20, 150)), (jx + k * 7, y - k * 7))
            if slot.new:  # lit up
                ring = Image.new("RGBA", (jacket + 60, jacket + 60), (0, 0, 0, 0))
                ImageDraw.Draw(ring).rounded_rectangle((22, 22, jacket + 38, jacket + 38), radius=12, fill=(*acc, 255))
                _over(canvas, ring.filter(ImageFilter.GaussianBlur(12)), (jx - 30, y - 30))
            _framed_jacket(canvas, jx, y, jacket, e.jacket_path, e.difficulty)
            if not slot.new:
                _over(canvas, Image.new("RGBA", (jacket, jacket), (8, 10, 20, 110)), (jx, y))
            draw = ImageDraw.Draw(canvas)
            if slot.new:
                tw = int(draw.textlength("NEW", font=num(18))) + 14
                pill = _gradient_fill((tw, 22), [(255, 120, 150), (255, 200, 90)])
                pill.putalpha(_rounded_mask((tw, 22), 8))
                _over(canvas, pill, (jx - 4, y - 8))
                draw = ImageDraw.Draw(canvas)
                draw.text((jx - 4 + tw / 2, y + 3), "NEW", font=num(18), fill=(40, 20, 30), anchor="mm")
            if slot.count > 1:
                _draw_count_pill(canvas, jx + jacket + 10, y - 14, slot.count)
                draw = ImageDraw.Draw(canvas)
            draw.text((cx + col / 2, y + jacket + 26), e.score_text, font=num(24),
                      fill=st["text"] if slot.new else st["muted"], anchor="ms")
            sub = e.rank + (f" · {e.lamp}" if e.lamp else "")
            draw.text((cx + col / 2, y + jacket + 43), sub, font=num(16, "SemiBold"),
                      fill=RANK_COLORS.get(e.rank, st["muted"]), anchor="ms")
            y += slot_h
    if not credits:
        draw.text((width / 2, lane_y + 60), "플레이 기록이 없어요", font=cjk(22), fill=st["muted"],
                  anchor="mm")
    return encode(canvas)


def render_profile(game: str, name: str, rating: str | None, title: str | None, title_rarity: str | None,
                   level: str | None, icon: bytes | None, plate: bytes | None) -> bytes:
    """Profile card: nameplate, icon, title, level, name and the rating plate."""
    from types import SimpleNamespace

    theme = THEMES[game]
    st = STYLES["version"]
    width, height = MARGIN * 2 + 2 * CARD_W + GAP_X, 220
    canvas = _rgb(_background(SimpleNamespace(game=game, old=[], new=[], icon=icon), (width, height), theme, st))

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
    _over(canvas, card, (cx, cy))
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
        _over(canvas, out, (right - size, cy + 14))
        right -= size + 16

    if title:
        colors = TITLE_COLORS.get((title_rarity or "normal").lower(), TITLE_COLORS["normal"])
        t = _fit(draw, title, cjk(16), right - tx - 40)
        tw = int(draw.textlength(t, font=cjk(16))) + 40
        rim = _gradient_fill((tw, 30), colors)
        rim.putalpha(_rounded_mask((tw, 30), 15))
        _over(canvas, rim, (tx, cy + 16))
        core = Image.new("RGBA", (tw - 4, 26), (0, 0, 0, 0))
        core.paste(Image.new("RGBA", core.size, (14, 12, 24, 215)), (0, 0), _rounded_mask(core.size, 13))
        _over(canvas, core, (tx + 2, cy + 18))
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
             "ULT": "ULTIMA", "WE": "WORLD'S END", "宴": "U·TA·GE"}
ULTIMA_RIM = (210, 20, 50)


def _page(game: str, size: tuple[int, int]) -> Image.Image:
    from types import SimpleNamespace

    return _rgb(_background(SimpleNamespace(game=game, old=[], new=[], icon=None), size, THEMES[game],
                            STYLES["version"]))


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
    _over(canvas, panel, (x0, y0))


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
    elif label == "WE":
        color = (245, 245, 248)
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
RANDOM_SLOTS = 4  # /random picks at most this many


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
    # always as wide as four cards, so every result shows at the same size in Discord
    width = MARGIN * 2 + RANDOM_SLOTS * PICK_W + (RANDOM_SLOTS - 1) * gap
    height = header + card_h + 34
    canvas = _page(game, (width, height))
    _page_header(canvas, game, "RANDOM", level_label)

    # fewer cards spread out a little instead of huddling in the middle
    spread = {4: gap, 3: 64, 2: 90}.get(len(picks), gap)
    x0 = (width - (len(picks) * PICK_W + (len(picks) - 1) * spread)) // 2
    for i, p in enumerate(picks):
        x, y = x0 + i * (PICK_W + spread), header
        _panel(canvas, (x, y, x + PICK_W, y + card_h), theme["card"])
        jx, jy = x + (PICK_W - PICK_JACKET) // 2, y + 16
        _framed_jacket(canvas, jx, jy, PICK_JACKET, p.get("jacket"), p["difficulty"])
        by = jy + PICK_JACKET + 14
        _diff_bar(canvas, (jx - 4, by, jx + PICK_JACKET + 3, by + 40), p["difficulty"],
                  _const_text(p["level"], p["const"]))

        draw = ImageDraw.Draw(canvas)
        ty = by + 54
        tf = cjk(20)
        lines = _wrap(draw, p["title"], tf, PICK_W - 32, 2)
        if len(lines) == 2 and len(lines[1].strip()) <= 2:  # don't leave a lone "！" on the second line
            tf = cjk(18)
            lines = _wrap(draw, p["title"], tf, PICK_W - 32, 2)
        for line in lines:
            draw.text((x + 16, ty), line, font=tf, fill=WHITE)
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


PROGRESS_H = 104  # rating panel under the header of a /recommend page


def _draw_progress(canvas: Image.Image, game: str, box: tuple[int, int, int, int], progress: dict) -> None:
    """Rating now » after, the gain, and a bar split into what each chart adds (in its difficulty color).

    progress: before, after, gain (texts), label, parts [(share of the gain, difficulty)].
    """
    x0, y0, x1, y1 = box
    _panel(canvas, box, THEMES[game]["card"], radius=16)
    draw = ImageDraw.Draw(canvas)
    draw.text((x0 + 24, y0 + 16), "RATING", font=num(17, "SemiBold"), fill=MUTED)
    base = y0 + 70
    x = x0 + 24
    draw.text((x, base), progress["before"], font=num(40), fill=WHITE, anchor="ls")
    x += draw.textlength(progress["before"], font=num(40)) + 14
    draw.text((x, base - 4), "»", font=num(30), fill=MUTED, anchor="ls")
    x += draw.textlength("»", font=num(30)) + 14
    draw.text((x, base), progress["after"], font=num(40), fill=MAX_RATING, anchor="ls")
    x += draw.textlength(progress["after"], font=num(40)) + 16
    pill_w = int(draw.textlength(progress["gain"], font=num(20))) + (20 + 6) // 2 - 1 + 22  # as _up_pill
    x = _up_pill(canvas, int(x) + pill_w, base - 29, progress["gain"], 20) + pill_w
    draw = ImageDraw.Draw(canvas)

    # the bar: from now (left) to all done (right), one piece per chart
    bx0, bx1 = int(x + 36), x1 - 24
    if bx1 - bx0 < 120:
        return
    draw.text((bx0, y0 + 18), progress["label"], font=cjk(15), fill=MUTED, anchor="lt")
    by, bh = base - 22, 18
    _panel(canvas, (bx0, by, bx1, by + bh), (0, 0, 0), alpha=110, radius=bh // 2, outline=False)
    parts = [(max(0.0, share), diff) for share, diff in progress["parts"]]
    total = sum(share for share, _ in parts) or 1.0
    bar = Image.new("RGBA", (bx1 - bx0, bh), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    px = 0.0
    for i, (share, diff) in enumerate(parts):
        w = (bx1 - bx0) * share / total
        color = _diff_info(diff)[2]
        bd.rectangle((round(px), 0, round(px + w) - (2 if i < len(parts) - 1 else 0), bh), fill=(*color, 255))
        px += w
    mask = _rounded_mask(bar.size, bh // 2)
    bar.putalpha(Image.composite(bar.getchannel("A"), Image.new("L", bar.size, 0), mask))
    _over(canvas, bar, (bx0, by))
    draw = ImageDraw.Draw(canvas)
    draw.text((bx0, by + bh + 8), progress["before"], font=num(15, "Medium"), fill=MUTED, anchor="lt")
    draw.text((bx1, by + bh + 8), progress["after"], font=num(15, "Medium"), fill=MAX_RATING, anchor="rt")


def render_chart_list(game: str, kicker: str, title: str, rows: list[dict], sub: str | None = None,
                      footer: str | None = None, columns: int = 3, group: bool = False,
                      scale: float | None = None, progress: dict | None = None) -> bytes:
    """Charts as tiles: jacket, title, difficulty/level and a value on the right.

    rows: title, difficulty, level, const, jacket, right (big text), and optionally right_sub (small text
    under it), sub_line (after the difficulty), note (a line along the bottom of the tile) and genre
    (a chip at the end of the note).
    group=True puts a heading above each run of charts with the same constant.
    progress: a rating panel under the header (see _draw_progress).
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
    top = 116 + (PROGRESS_H if progress else 0)
    y, col, last = top, 0, None
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

    def draw_item(canvas, kind, x, y, payload):
        draw = ImageDraw.Draw(canvas)
        if kind == "head":
            draw.text((x + 2, y + 18), str(payload), font=num(28), fill=theme["accent"], anchor="lm")
            lw = draw.textlength(str(payload), font=num(28)) + 14
            draw.line((x + lw, y + 19, width - MARGIN, y + 19), fill=(255, 255, 255, 50), width=1)
            return
        row = payload
        _panel(canvas, (x, y, x + tile_w, y + tile_h), theme["card"], radius=14)
        _framed_jacket(canvas, x + 12, y + 10, js, row.get("jacket"), row["difficulty"])
        draw = ImageDraw.Draw(canvas)
        label, name, color, _ = _diff_info(row["difficulty"])
        right = row.get("right") or ""
        rw = int(draw.textlength(right, font=num(34 if big else 26))) + 20 if right else 0
        tx = x + 12 + js + 16
        # without a note line the genre chip goes under `right`, where right_sub would be
        genre_under = bool(right and row.get("genre") and not row.get("note") and not row.get("right_sub"))
        under = bool(right and row.get("right_sub")) or genre_under
        if right and row.get("right_sub"):  # the small line under `right` sits beside the sub_line
            sub_font = num(17, "Medium") if row["right_sub"].isascii() else cjk(14)
            sub_w = int(draw.textlength(row["right_sub"], font=sub_font)) + 20
        elif genre_under:
            sub_w = int(draw.textlength(row["genre"], font=cjk(13))) + 18 + 20
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
            sub_room = text_w + rw - max(rw, sub_w) if under else text_w
            draw.text((sx, info_y), _fit(draw, row["sub_line"], cjk(14), max(0, sub_room - int(sx - tx))),
                      font=cjk(14), fill=MUTED, anchor="ls")
        if right:
            if under:
                draw.text((x + tile_w - 16, y + top_h / 2 - 2), right, font=num(34), fill=MAX_RATING, anchor="rs")
            if row.get("right_sub"):
                draw.text((x + tile_w - 16, y + top_h / 2 + 22), row["right_sub"], font=sub_font, fill=MUTED,
                          anchor="rs")
            elif genre_under:
                gw = sub_w - 20
                gx, gy = x + tile_w - 16 - gw, int(y + top_h / 2 + 22 - 17)
                _panel(canvas, (gx, gy, gx + gw, gy + 22), theme["accent"], alpha=45, radius=11, outline=False)
                draw = ImageDraw.Draw(canvas)
                draw.text((gx + gw // 2, gy + 11), row["genre"], font=cjk(13), fill=WHITE, anchor="mm")
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

    # one strip per row of tiles / heading, so LOW_MEMORY can draw a smaller page strip by strip
    strips = [(0, 116, lambda c, dy: _page_header(c, game, kicker, title, sub))]
    if progress:
        strips.append((116, top, lambda c, dy: _draw_progress(
            c, game, (MARGIN, 116 + dy, width - MARGIN, top - 14 + dy), progress)))
    rows_at: dict[int, list] = {}
    for item in items:
        rows_at.setdefault(item[2], []).append(item)
    for y, group_items in rows_at.items():
        kind = group_items[0][0]
        bottom = y + (40 if kind == "head" else tile_h + gap)

        def strip(c, dy, group_items=group_items):
            for kind, x, iy, payload in group_items:
                draw_item(c, kind, x, iy + dy, payload)

        strips.append((y, bottom, strip))
    if footer:
        strips.append((height - 44, height, lambda c, dy: ImageDraw.Draw(c).text(
            (width - MARGIN, height - 26 + dy), footer, font=cjk(15), fill=MUTED, anchor="rm")))
    return _paint(strips, (width, height), lambda size: _page(game, size), LIST_SCALE if scale is None else scale)


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


# ------------------------------------------------------------------- memory

_render_lock = __import__("threading").Lock()


def _one_at_a_time(fn):
    """Draw one image at a time (renders run in worker threads), then give the memory back,
    so a few people asking at once don't stack their peaks."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _render_lock:
            try:
                return fn(*args, **kwargs)
            finally:
                release_memory()

    return wrapper


render_b50 = _one_at_a_time(render_b50)
render_credit = _one_at_a_time(render_credit)
render_day = _one_at_a_time(render_day)
render_profile = _one_at_a_time(render_profile)
render_random = _one_at_a_time(render_random)
render_song = _one_at_a_time(render_song)
render_chart_list = _one_at_a_time(render_chart_list)
render_scores = _one_at_a_time(render_scores)
