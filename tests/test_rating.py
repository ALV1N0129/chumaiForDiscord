from fractions import Fraction

import pytest

from chumai import rating


@pytest.mark.parametrize(
    "const, percent, expected",
    [
        (15.0, 100.5, 337),
        (14.7, 100.5, 330),
        (13.7, 100.5, 308),
        (14.7, 101.0, 330),  # achievement is capped at 100.5
        (14.0, 100.0, 302),
        (14.0, 99.5, 293),
        (13.0, 97.0, 252),
        (13.0, 0.0, 0),
    ],
)
def test_maimai_rating(const, percent, expected):
    assert rating.maimai_rating(const, percent) == expected


@pytest.mark.parametrize(
    "percent, rank",
    [(100.5, "SSS+"), (100.2, "SSS"), (99.7, "SS+"), (99.0, "SS"), (98.5, "S+"), (97.1, "S"), (95, "AAA"), (5, "D")],
)
def test_maimai_rank(percent, rank):
    assert rating.maimai_rank(percent) == rank


@pytest.mark.parametrize(
    "const, score, expected",
    [
        (14.7, 1_010_000, "16.85"),
        (14.7, 1_009_000, "16.85"),
        (14.7, 1_008_000, "16.75"),
        (14.7, 1_007_500, "16.70"),
        (14.7, 1_006_000, "16.40"),
        (14.7, 1_005_000, "16.20"),
        (14.7, 1_000_000, "15.70"),
        (14.7, 987_500, "15.20"),
        (14.7, 975_000, "14.70"),
        (14.7, 950_000, "13.20"),
        (14.7, 900_000, "9.70"),
        (14.7, 400_000, "0"),
    ],
)
def test_chunithm_rating(const, score, expected):
    assert rating.chunithm_rating(const, score) == Fraction(expected)


def test_chunithm_rank():
    assert rating.chunithm_rank(1_009_000) == "SSS+"
    assert rating.chunithm_rank(1_008_999) == "SSS"
    assert rating.chunithm_rank(999_999) == "S+"
