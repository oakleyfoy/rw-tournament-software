"""
Canonical parser for tournament court names.

Handles both string ("1,5,6") and list (["1","5","6"]) inputs so we never
silently corrupt labels (e.g. list("1,5,6") -> ['1', ',', '5', ...]).
"""
from typing import List, Optional, Union


def court_label_for_index(court_names: Optional[Union[str, List[str]]], court_number: int) -> str:
    """
    Return the scalar court label for a given court index (1-based).
    Never pass a list; always use this for ScheduleSlot.court_label.
    """
    labels = parse_court_names(court_names)
    if labels and 1 <= court_number <= len(labels):
        return str(labels[court_number - 1])
    return str(court_number)


def parse_court_names(court_names: Optional[Union[str, List[str]]]) -> List[str]:
    """
    Normalize court_names to a list of non-empty strings.

    - None or "" -> []
    - String (e.g. "1,5,6") -> split on commas, strip whitespace, drop empties -> ["1","5","6"]
    - List (e.g. ["1","5","6"]) -> coerce each to str(x).strip(), drop empties
    """
    if court_names is None:
        return []
    if isinstance(court_names, str):
        s = court_names.strip()
        if not s:
            return []
        return [x.strip() for x in s.split(",") if x.strip()]
    if isinstance(court_names, list):
        return [str(x).strip() for x in court_names if str(x).strip()]
    return []
