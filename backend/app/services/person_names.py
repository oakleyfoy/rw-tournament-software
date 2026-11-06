"""First names that stay aligned with the text message.

A text uses the team display name, which keeps a compound given name
("Dee Dee", "Mary Ann") and keeps two players who share a first name apart.
Photo labels, court cards, and roster matching have to use that same given
name. The first word alone is a different person.
"""

from __future__ import annotations

import re

_CLONE_SUFFIX = re.compile(r"\s+\(\d+\)$")
_TOKEN = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*", re.IGNORECASE)


def _clean(value: str | None) -> str:
    return _CLONE_SUFFIX.sub("", " ".join((value or "").split())).strip()


def _segments(value: str | None) -> list[str]:
    raw = _clean(value)
    return [part.strip() for part in raw.split(",") if part.strip()]


def split_people(value: str | None) -> list[str]:
    raw = _clean(value)
    if not raw:
        return []
    if "/" in raw:
        parts = [part.strip() for part in raw.split("/") if part.strip()]
    elif "&" in raw:
        parts = [part.strip() for part in raw.split("&") if part.strip()]
    else:
        parts = [raw]
    return parts[:2]


def _norm_tokens(value: str) -> list[str]:
    return [token.casefold() for token in _TOKEN.findall(value or "")]


def name_identity(value: str | None) -> tuple[list[str], str | None]:
    """Given-name tokens and the surname.

    "Dee Dee Worley, Alpharetta, GA" -> (["dee", "dee"], "worley")
    "Mary Ann Smith" -> (["mary", "ann"], "smith")
    "Smith, Mary Ann" -> (["mary", "ann"], "smith")
    "Dee Dee" -> (["dee", "dee"], None)
    "Heather Robinson" -> (["heather"], "robinson")
    """
    parts = _segments(value)
    if not parts:
        return [], None
    if len(parts) >= 2 and len(parts[0].split()) == 1:
        given = _norm_tokens(parts[1])
        last = _norm_tokens(parts[0])
        return given, (last[0] if last else None)
    words = _norm_tokens(parts[0])
    if len(words) >= 3:
        return words[:-1], words[-1]
    if len(words) == 2 and words[0] == words[1]:
        return words, None
    if len(words) == 2:
        return [words[0]], words[1]
    if len(words) == 1:
        return words, None
    return [], None


def given_name(value: str | None) -> str:
    """Given name with the original casing. Surnames and hometowns are dropped.

    A repeated or multi-word given name stays whole: "Dee Dee Worley" -> "Dee Dee"
    and "Mary Ann Smith" -> "Mary Ann". "Heather Robinson" stays "Heather".
    """
    parts = _segments(value)
    if not parts:
        return ""
    if len(parts) >= 2 and len(parts[0].split()) == 1:
        return " ".join(parts[1].split())
    words = parts[0].split()
    if len(words) >= 3:
        return " ".join(words[:-1])
    if len(words) == 2 and words[0].casefold() == words[1].casefold():
        return " ".join(words)
    if len(words) >= 1:
        return words[0]
    return ""


def short_partnership(value: str | None) -> str:
    names = [given_name(side) for side in split_people(value)]
    names = [name for name in names if name]
    return " / ".join(names)


def _last_names_conflict(left_last: str | None, right_last: str | None) -> bool:
    return bool(left_last and right_last and left_last != right_last)


def same_person_for_label(left: str | None, right: str | None) -> bool:
    """True when both sides are the same given name and the surnames do not disagree.

    "Dee Dee" is "Dee Dee Worley". "Dee" is not. "Lisa Jones" is not "Lisa Smith".
    """
    left_given, left_last = name_identity(left)
    right_given, right_last = name_identity(right)
    if not left_given or left_given != right_given:
        return False
    return not _last_names_conflict(left_last, right_last)


def partnership_same_people(display_name: str | None, legal_name: str | None) -> bool:
    display_sides = split_people(display_name)
    legal_sides = split_people(legal_name)
    if not display_sides or not legal_sides or len(display_sides) != len(legal_sides):
        return False
    if all(same_person_for_label(left, right) for left, right in zip(display_sides, legal_sides)):
        return True
    if len(display_sides) == 2 and same_person_for_label(display_sides[0], legal_sides[1]) and same_person_for_label(
        display_sides[1], legal_sides[0]
    ):
        return True
    return False


def label_matching_text(display_name: str | None, legal_name: str | None) -> str:
    """Name to show with a photo.

    The text message is the display name. Use it when it is the same people as
    the legal team name, so "Dee Dee / Dennis" and "Lisa Jones / Heather" stay
    intact. A stale display name that names different people is ignored, and
    the legal name is shortened without dropping a compound given name.
    """
    legal = (legal_name or "").strip()
    display = (display_name or "").strip()
    short = short_partnership(legal)
    if display and partnership_same_people(display, legal):
        return display
    return short or display


def restores_compound_given_name(longer: str | None, shorter: str | None) -> bool:
    """True when `longer` puts back a given-name word that `shorter` dropped."""
    longer_sides = split_people(longer)
    shorter_sides = split_people(shorter)
    if not longer_sides or len(longer_sides) != len(shorter_sides):
        return False
    extended = False
    for long_side, short_side in zip(longer_sides, shorter_sides):
        long_given, _long_last = name_identity(long_side)
        short_given, _short_last = name_identity(short_side)
        if not long_given or not short_given:
            return False
        if long_given == short_given:
            continue
        if len(long_given) > len(short_given) and long_given[: len(short_given)] == short_given:
            extended = True
            continue
        return False
    return extended


def roster_names_match(slot_name: str | None, player_name: str | None) -> bool:
    """Same person for a roster slot.

    The whole given name has to match. "Dee Dee Worley" is not "Dee Worley",
    and "Mary Ann Smith" is not "Mary Smith". A single first name never matches
    every player who has that first name.
    """
    slot = " ".join((slot_name or "").split())
    player = " ".join((player_name or "").split())
    if not slot or not player:
        return False
    slot_key = " ".join(_norm_tokens(slot))
    player_key = " ".join(_norm_tokens(player))
    if slot_key and slot_key == player_key:
        return True
    slot_given, slot_last = name_identity(slot)
    player_given, player_last = name_identity(player)
    if slot_given and slot_given == player_given:
        if slot_last and player_last:
            return slot_last == player_last
        return len(slot_given) >= 2
    # "Mary Ann" is the given name of "Mary Ann Smith", not the surname Ann.
    slot_flat = slot_given + ([slot_last] if slot_last else [])
    player_flat = player_given + ([player_last] if player_last else [])
    if len(slot_flat) >= 2 and slot_flat == player_given:
        return True
    if len(player_flat) >= 2 and player_flat == slot_given:
        return True
    return False


def photo_name_for_slot(text_name: str | None, legal_name: str | None, linked_name: str | None) -> str:
    """Name printed on this team's photo.

    A linked player is used only when they are the same person as this team
    slot. Another player who shares a first name, or only the first word of a
    double name, is not this photo.
    """
    anchor = (legal_name or text_name or "").strip()
    linked = (linked_name or "").strip()
    if linked and anchor and roster_names_match(anchor, linked):
        return linked if len(linked) >= len(anchor) else anchor
    if anchor:
        return anchor
    return linked or "Partner not on file"
