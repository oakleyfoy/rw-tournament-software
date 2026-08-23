"""Team rating rules reused from RW-OS NTRP Combined (sum, not average)."""

from __future__ import annotations

from typing import Optional

RATING_STATUS_COMPLETE = "complete"
RATING_STATUS_PARTIAL = "partial"
RATING_STATUS_MISSING = "missing"

# RW-OS Event Team Partner report: NTRP Combined = player1 + player2.
TEAM_RATING_FORMULA = "sum_of_player_ntrp"
TEAM_RATING_SOURCE_FIELDS = ("ntrpRating", "NTRP_Rating", "NTRP")


def parse_rating(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number != number:  # NaN
            return None
        return number
    text = str(value).strip()
    if not text or text == "-":
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if number != number:
        return None
    return number


def classify_rating_status(player1_rating: Optional[float], player2_rating: Optional[float]) -> str:
    has_p1 = player1_rating is not None
    has_p2 = player2_rating is not None
    if has_p1 and has_p2:
        return RATING_STATUS_COMPLETE
    if has_p1 or has_p2:
        return RATING_STATUS_PARTIAL
    return RATING_STATUS_MISSING


def compute_team_rating(player1_rating: Optional[float], player2_rating: Optional[float]) -> Optional[float]:
    """Sum available player NTRP ratings. Missing values are not coerced to 0.0."""
    parts = [rating for rating in (player1_rating, player2_rating) if rating is not None]
    if not parts:
        return None
    return round(sum(parts), 4)
