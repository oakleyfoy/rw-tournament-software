"""Normalized draw catalog shared with RW-OS tournamentDrawCatalog."""

from __future__ import annotations

from typing import Optional

MAIN_DRAW_KINDS = ("womens", "mens", "mixed")
WAITLIST_DRAW_KINDS = ("womens_waitlist", "mens_waitlist", "mixed_waitlist")

DRAW_LABELS = {
    "womens": "Women's",
    "mens": "Men's",
    "mixed": "Mixed",
    "womens_waitlist": "Women's Waitlisted",
    "mens_waitlist": "Men's Waitlisted",
    "mixed_waitlist": "Mixed Waitlisted",
}


def _normalize_draw_match_key(raw: str) -> str:
    key = (
        raw.strip()
        .lower()
        .replace("'", "")
        .replace("'", "")
        .replace("´", "")
        .replace("`", "")
        .replace("(", " ")
        .replace(")", " ")
    )
    cleaned = []
    for ch in key:
        cleaned.append(ch if ch.isalnum() else " ")
    return " ".join("".join(cleaned).split())


def _is_waitlist_draw_key(key: str) -> bool:
    return "waitlist" in key or "wait listed" in key or "waitlisted" in key


def _resolve_base_draw_kind(key: str) -> Optional[str]:
    tokens = f" {key} "
    if " women " in tokens or " womens " in tokens:
        return "womens"
    if " mixed " in tokens:
        return "mixed"
    if " men " in tokens or " mens " in tokens:
        return "mens"
    return None


def resolve_draw_kind(raw: Optional[str]) -> Optional[str]:
    key = _normalize_draw_match_key(raw or "")
    if not key:
        return None
    base = _resolve_base_draw_kind(key)
    if not base:
        return None
    if _is_waitlist_draw_key(key):
        return f"{base}_waitlist"
    return base


def normalize_draw_label(raw: Optional[str]) -> str:
    trimmed = (raw or "").strip()
    if not trimmed:
        return ""
    kind = resolve_draw_kind(trimmed)
    if not kind:
        return trimmed
    return DRAW_LABELS.get(kind, trimmed)


def draw_kind_group_key(raw: Optional[str]) -> str:
    kind = resolve_draw_kind(raw)
    return kind or _normalize_draw_match_key(raw or "")


def is_known_draw_label(raw: Optional[str]) -> bool:
    return resolve_draw_kind(raw) is not None


def is_waitlist_draw_kind(kind: Optional[str]) -> bool:
    return bool(kind) and kind.endswith("_waitlist")


def main_draw_kind(kind: Optional[str]) -> Optional[str]:
    if not kind:
        return None
    if kind.endswith("_waitlist"):
        return kind[: -len("_waitlist")]
    return kind


def bracket_family_label(draw_kind: str) -> str:
    base = main_draw_kind(draw_kind) or draw_kind
    return DRAW_LABELS.get(base, base.title())
