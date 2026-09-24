"""Shared helpers for round-robin match_code → pool grouping (public draws / desk)."""

from __future__ import annotations

import re
from typing import Optional

# WF_10 Sunday cross / losers placement (not a single pool RR).
WF10_PLACEMENT_POOL_CODE = "WF10_PLACEMENT"

_WIN_RR_RE = re.compile(r"_WIN_(?:FRI|SAT1|SAT2)_([AB])\d+", re.IGNORECASE)
_FUN_RR_RE = re.compile(r"_FUN_(?:FRI|SAT1|SAT2)_\d+", re.IGNORECASE)
_LOSS_RR_RE = re.compile(r"_LOSS_(?:FRI|SAT1|SAT2)_\d+", re.IGNORECASE)
_WF10_SUN_RE = re.compile(r"_(?:WIN|LOSS)_SUN_\d+", re.IGNORECASE)


def is_wf10_sunday_placement_code(match_code: Optional[str]) -> bool:
    if not match_code:
        return False
    return bool(_WF10_SUN_RE.search(match_code.upper()))


def rr_pool_code_for_match(match_code: Optional[str]) -> Optional[str]:
    """Resolve pool code for a pool round-robin match.

    Handles:
    - Standard RR pools (``..._POOLA_RR_01``)
    - WF_14 loser-flight consolation (``..._CONS_<DAYTAG>_<POOL><SEQ>``)
    - WF_10 winners/fun/losers RR (``..._WIN_FRI_A01``, ``..._FUN_FRI_01``, ``..._LOSS_FRI_01``)
    """
    if not match_code:
        return None
    upper = match_code.upper()

    if "_RR_" in upper:
        head = match_code.split("_RR_")[0]
        return head.split("_")[-1].upper() or None

    if "_CONS_" in upper:
        # Sunday cross-placement is not a single-pool RR.
        if "_CONS_SUN_" in upper:
            return None
        last = upper.split("_")[-1]  # e.g. "C01" or "01"
        if last and last[0].isalpha():
            return f"POOL{last[0]}"
        return None

    win = _WIN_RR_RE.search(upper)
    if win:
        return f"POOL{win.group(1)}"

    if _FUN_RR_RE.search(upper):
        return "FUN"

    if _LOSS_RR_RE.search(upper):
        # Losers 4-team RR surfaces as Pool C (alongside winners A/B).
        return "POOLC"

    return None


def is_public_rr_pool_match_code(match_code: Optional[str]) -> bool:
    """True when a match_type=RR row should appear on the public RR board / standings."""
    return rr_pool_code_for_match(match_code) is not None
