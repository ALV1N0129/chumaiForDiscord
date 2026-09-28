"""Per-chart rating formulas for maimai DX and CHUNITHM.

Everything is done in integer / Fraction arithmetic so that rounding matches
the game (floating point turns e.g. 13.7 * 22.4 * 100.5 into 308.4119999...).
"""

from __future__ import annotations

from fractions import Fraction

# (minimum achievement %, coefficient) — checked top to bottom.
MAIMAI_RANK_FACTORS: list[tuple[str, Fraction, Fraction]] = [
    ("SSS+", Fraction("100.5"), Fraction("22.4")),
    ("SSS", Fraction("100.4999"), Fraction("22.2")),
    ("SSS", Fraction("100"), Fraction("21.6")),
    ("SS+", Fraction("99.9999"), Fraction("21.4")),
    ("SS+", Fraction("99.5"), Fraction("21.1")),
    ("SS", Fraction("99"), Fraction("20.8")),
    ("S+", Fraction("98.9999"), Fraction("20.6")),
    ("S+", Fraction("98"), Fraction("20.3")),
    ("S", Fraction("97"), Fraction("20.0")),
    ("AAA", Fraction("96.9999"), Fraction("17.6")),
    ("AAA", Fraction("94"), Fraction("16.8")),
    ("AA", Fraction("90"), Fraction("15.2")),
    ("A", Fraction("80"), Fraction("13.6")),
    ("BBB", Fraction("79.9999"), Fraction("12.8")),
    ("BBB", Fraction("75"), Fraction("12.0")),
    ("BB", Fraction("70"), Fraction("11.2")),
    ("B", Fraction("60"), Fraction("9.6")),
    ("C", Fraction("50"), Fraction("8.0")),
    ("D", Fraction("40"), Fraction("6.4")),
    ("D", Fraction("30"), Fraction("4.8")),
    ("D", Fraction("20"), Fraction("3.2")),
    ("D", Fraction("10"), Fraction("1.6")),
    ("D", Fraction("0"), Fraction("0")),
]


def _frac(x: float | str | Fraction) -> Fraction:
    # str() first so 13.7 becomes exactly 137/10, not the nearest binary float.
    return x if isinstance(x, Fraction) else Fraction(str(x))


def maimai_rank(percent: float) -> str:
    p = _frac(percent)
    for rank, threshold, _ in MAIMAI_RANK_FACTORS:
        if p >= threshold:
            return rank
    return "D"


def maimai_rating(level_const: float, percent: float) -> int:
    """Rating of a single maimai DX chart (integer, as shown in game)."""
    p = _frac(percent)
    for _, threshold, factor in MAIMAI_RANK_FACTORS:
        if p >= threshold:
            capped = min(p, Fraction("100.5"))
            return int(_frac(level_const) * factor * capped / 100)
    return 0


CHUNITHM_RANKS: list[tuple[int, str]] = [
    (1_009_000, "SSS+"),
    (1_007_500, "SSS"),
    (1_005_000, "SS+"),
    (1_000_000, "SS"),
    (990_000, "S+"),
    (975_000, "S"),
    (950_000, "AAA"),
    (925_000, "AA"),
    (900_000, "A"),
    (800_000, "BBB"),
    (700_000, "BB"),
    (600_000, "B"),
    (500_000, "C"),
    (0, "D"),
]


def chunithm_rank(score: int) -> str:
    for threshold, rank in CHUNITHM_RANKS:
        if score >= threshold:
            return rank
    return "D"


def chunithm_rating(level_const: float, score: int) -> Fraction:
    """Rating of a single CHUNITHM chart, truncated to 0.01."""
    c = _frac(level_const) * 100  # work in hundredths
    s = int(score)

    if s >= 1_009_000:
        r = c + 215
    elif s >= 1_007_500:
        r = c + 200 + (s - 1_007_500) // 100
    elif s >= 1_005_000:
        r = c + 150 + (s - 1_005_000) // 50
    elif s >= 1_000_000:
        r = c + 100 + (s - 1_000_000) // 100
    elif s >= 975_000:
        r = c + (s - 975_000) // 250
    elif s >= 925_000:
        r = c - 300 + Fraction(300 * (s - 925_000), 50_000)
    elif s >= 900_000:
        r = c - 500 + Fraction(200 * (s - 900_000), 25_000)
    elif s >= 800_000:
        half = (c - 500) / 2
        r = half + half * Fraction(s - 800_000, 100_000)
    elif s >= 500_000:
        half = (c - 500) / 2
        r = half * Fraction(s - 500_000, 300_000)
    else:
        r = Fraction(0)

    r = max(Fraction(0), r)
    return Fraction(int(r), 100)  # truncate to 2 decimals


def truncate(value: Fraction, places: int = 2) -> Fraction:
    scale = 10**places
    return Fraction(int(value * scale), scale)
