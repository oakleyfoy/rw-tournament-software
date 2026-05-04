"""Parse and serialize tournament-level per-day event ID ordering for schedule policy."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def parse_event_schedule_day_orders_raw(raw: Optional[str]) -> Optional[List[List[int]]]:
    """
    Parse tournament.event_schedule_day_orders_json into a list of lists by day index.

    Canonical shape: {"day_orders": [[event_id, ...], ...]}
    Also accepts legacy numeric-string keys {"1": [...], "2": [...]} (sorted by key).
    Returns None if unset or invalid.
    """
    if not raw or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    if "day_orders" in data:
        arr = data.get("day_orders")
        if not isinstance(arr, list):
            return None
        return [_normalize_id_row(row) for row in arr]

    # Legacy: top-level keys "1", "2", ...
    numeric_keys = []
    for k, v in data.items():
        if isinstance(k, str) and k.isdigit():
            numeric_keys.append((int(k), v))
        elif isinstance(k, int):
            numeric_keys.append((k, v))
    if not numeric_keys:
        return None
    numeric_keys.sort(key=lambda x: x[0])
    return [_normalize_id_row(v) for _, v in numeric_keys]


def _normalize_id_row(row: Any) -> List[int]:
    if not isinstance(row, list):
        return []
    out: List[int] = []
    seen: set[int] = set()
    for x in row:
        eid: Optional[int] = None
        if isinstance(x, int) and x > 0:
            eid = x
        elif isinstance(x, str) and x.strip().isdigit():
            eid = int(x.strip())
        if eid is not None and eid not in seen:
            seen.add(eid)
            out.append(eid)
    return out


def serialize_event_schedule_day_orders(day_orders: List[List[int]]) -> str:
    """JSON string for persistence."""
    return json.dumps({"day_orders": day_orders})


def remap_event_schedule_day_orders_json(
    raw: Optional[str],
    event_id_map: Dict[int, int],
) -> Optional[str]:
    """Remap event IDs after tournament duplicate; drop unmapped IDs."""
    parsed = parse_event_schedule_day_orders_raw(raw)
    if not parsed:
        return None
    remapped: List[List[int]] = []
    for row in parsed:
        new_row: List[int] = []
        seen: set[int] = set()
        for old_id in row:
            new_id = event_id_map.get(old_id)
            if new_id is not None and new_id not in seen:
                seen.add(new_id)
                new_row.append(new_id)
        remapped.append(new_row)
    if not any(remapped):
        return None
    return serialize_event_schedule_day_orders(remapped)


def event_ids_for_day(day_orders: Optional[List[List[int]]], day_index: int) -> List[int]:
    """
    Ordered event IDs for scheduling day_index (0-based).

    Resolution order:
    1. Walk backward from clamped index (same calendar row or last row if day_index
       exceeds the matrix), using the first non-empty row found — inherits from an
       earlier day when today's row is empty.
    2. If still empty (e.g. day 0 row blank but day 2 Draw Builder row is filled),
       walk forward from the clamped index for the first non-empty row so Saturday
       can reuse Sunday's explicit order without duplicating rows in the UI.

    If the matrix has fewer rows than slot days, the clamp reuses the last row for
    overflow days (unchanged).
    """
    if not day_orders or day_index < 0:
        return []
    capped = min(day_index, len(day_orders) - 1)

    idx = capped
    while idx >= 0:
        row = day_orders[idx]
        if row:
            return list(row)
        idx -= 1

    idx = capped + 1
    while idx < len(day_orders):
        row = day_orders[idx]
        if row:
            return list(row)
        idx += 1

    return []
