"""
Master Match Sequence Builder
=============================
Produces a single deterministic ranked list (1..N) of every match in a
tournament, ordered by the ideal playing sequence.  Works for any number
of events, any size, any number of tournament days (2, 3, or 4).

Algorithm:
  1. Events sorted largest-first (team_count DESC, event_id ASC tiebreak).
  2. Within each event, matches grouped into "team-rounds" — one round =
     every team plays once.  The (match_type, round_index) combination
     determines which team-round a match belongs to.
  3. Interleave across events: each event plays one team-round, then the
     next event, round-robin style.
  4. Within an event-round, matches sorted by match_id for determinism.

Day assignment:
  - 2 team-rounds per day (hard rule: no team plays > 2 matches/day).
  - If a day can't fit all its matches, overflow carries to next day.
  - Event rotation: each day starts with a different event from the
    largest tied group (Day 1 = A, Day 2 = B, Day 3 = C, etc.).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select

from app.models import Event, Match

# ── Phase ordering ───────────────────────────────────────────────────────
# Maps (match_type, round_index) to a phase number.
# The tens digit encodes the TEAM-ROUND (which match # it is for the team).
# The units digit encodes sub-ordering within a team-round:
#   MAIN=0, RR=1, CONSOLATION=2.
#
# This covers all known tournament structures:
#   - WF_TO_BRACKETS_8: WF(2) + MAIN(3) + CONS(2) = 5 matches
#   - WF_TO_POOLS_DYNAMIC: WF(2) + RR(up to 3) = up to 5 matches
#   - RR_ONLY: RR(3-5) matches
#   - Any mix of the above across events in one tournament.
#
PHASE_ORDER: Dict[Tuple[str, int], int] = {
    # Team Round 1: team's 1st match
    ("WF", 1): 10,
    # Team Round 2: team's 2nd match
    ("WF", 2): 20,
    # Team Round 3: team's 3rd match
    ("MAIN", 1): 30,            # MAIN QF
    ("RR", 1): 31,              # RR R1
    # Team Round 4: team's 4th match (MAIN, then RR, then CONS)
    ("MAIN", 2): 40,            # MAIN SF
    ("RR", 2): 41,              # RR R2
    ("CONSOLATION", 1): 42,     # CONS Semi (C1+C2)
    # Team Round 5: team's 5th match (MAIN, then RR, then CONS)
    ("MAIN", 3): 50,            # MAIN Final
    ("RR", 3): 51,              # RR R3
    ("CONSOLATION", 2): 52,     # CONS Final+ (C3+C4+C5)
    # Placement (if any)
    ("PLACEMENT", 1): 60,
}

# Fallback for unknown (match_type, round_index) combinations.
# Uses stage_base * 10 + round_index.  This ensures unknown combos
# still sort in a sensible order relative to known ones.
STAGE_ORDER_FALLBACK = {"WF": 0, "RR": 1, "MAIN": 2, "CONSOLATION": 3, "PLACEMENT": 4}


@dataclass
class RankedMatch:
    """One entry in the master sequence."""
    rank: int
    match_id: int
    match_code: str
    event_id: int
    event_name: str
    match_type: str
    round_index: int
    round_label: str        # e.g. "WF R1", "MAIN QF", "CONS R1"
    matches_in_round: int   # how many matches in this event-round
    global_round: int       # which interleave pass (0-based)


def _round_label(match_type: str, round_index: int) -> str:
    """Human-readable label for a round."""
    if match_type == "WF":
        return f"WF R{round_index}"
    if match_type == "RR":
        return f"RR R{round_index}"
    if match_type == "MAIN":
        labels = {1: "MAIN QF", 2: "MAIN SF", 3: "MAIN Final"}
        return labels.get(round_index, f"MAIN R{round_index}")
    if match_type == "CONSOLATION":
        labels = {1: "CONS Semi", 2: "CONS Final+"}
        return labels.get(round_index, f"CONS R{round_index}")
    if match_type == "PLACEMENT":
        return f"PLACE R{round_index}"
    return f"{match_type} R{round_index}"


def _phase_key(k: Tuple[str, int]) -> int:
    """Sort key for (match_type, round_index) → phase number."""
    if k in PHASE_ORDER:
        return PHASE_ORDER[k]
    return STAGE_ORDER_FALLBACK.get(k[0], 99) * 10 + k[1]


def _build_event_phase_map(
    matches: List[Match],
) -> Dict[int, Tuple[str, int, List[Match]]]:
    """
    Group an event's matches by phase number.

    Returns dict mapping phase_number → (match_type, round_index, [matches]).
    """
    groups: Dict[Tuple[str, int], List[Match]] = defaultdict(list)
    for m in matches:
        key = (m.match_type, m.round_index or 0)
        groups[key].append(m)

    # Sort each group's matches by match_id for determinism
    for key in groups:
        groups[key].sort(key=lambda m: m.id)

    # Map to phase number
    result: Dict[int, Tuple[str, int, List[Match]]] = {}
    for (mt, ri), match_list in groups.items():
        phase = _phase_key((mt, ri))
        result[phase] = (mt, ri, match_list)

    return result


def _rotate_events(events: List[Event], rotation: int) -> List[Event]:
    """
    Rotate event order among tied team_count groups.

    Only rotates within the largest tied group (the ones that share the
    highest team_count).  Smaller events stay at the end in their
    original order.
    """
    if not events or rotation == 0:
        return list(events)

    # Find the largest team_count group
    max_tc = events[0].team_count or 0
    top_group = [e for e in events if (e.team_count or 0) == max_tc]
    rest = [e for e in events if (e.team_count or 0) != max_tc]

    if len(top_group) <= 1:
        return list(events)  # nothing to rotate

    r = rotation % len(top_group)
    rotated_top = top_group[r:] + top_group[:r]
    return rotated_top + rest


def _compute_day_rotations(num_team_rounds: int) -> Dict[int, int]:
    """
    Auto-compute event rotation per team-round.

    Pairs 2 team-rounds per day.  Each day gets a different rotation
    offset so that a different event starts each day.

        Day 1 (rounds 0-1): rotation 0
        Day 2 (rounds 2-3): rotation 1
        Day 3 (rounds 4+):  rotation 2
        Day 4 (if any):     rotation 3
        ...
    """
    rotations: Dict[int, int] = {}
    for tr in range(num_team_rounds):
        day_idx = tr // 2   # 2 team-rounds per day
        rotations[tr] = day_idx
    return rotations


def build_master_sequence(
    session: Session,
    schedule_version_id: int,
    day_rotations: Optional[Dict[int, int]] = None,
) -> List[RankedMatch]:
    """
    Build the master match sequence for a schedule version.

    Args:
        day_rotations: optional mapping of team-round index (0-based)
            to event rotation offset.  If None, auto-computed from
            the number of team-rounds found in the match data
            (2 team-rounds per day, rotation increments each day).

    Returns a list of RankedMatch objects, ranked 1..N.
    """
    # Load matches
    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()
    if not all_matches:
        return []

    # Load events for this tournament
    tournament_id = all_matches[0].tournament_id
    events = session.exec(
        select(Event).where(Event.tournament_id == tournament_id)
    ).all()

    # Event ordering: largest team_count first, event_id tiebreak
    events_sorted = sorted(events, key=lambda e: (-(e.team_count or 0), e.id))

    # Group matches by event
    matches_by_event: Dict[int, List[Match]] = defaultdict(list)
    for m in all_matches:
        matches_by_event[m.event_id].append(m)

    # Build event phase maps (phase_number -> round data)
    event_phases: Dict[int, Dict[int, Tuple[str, int, List[Match]]]] = {}
    for e in events_sorted:
        event_phases[e.id] = _build_event_phase_map(matches_by_event.get(e.id, []))

    # Collect all phase numbers across all events, sorted
    all_phase_nums = sorted(set(
        ph for pm in event_phases.values() for ph in pm.keys()
    ))

    # Group phases into team-rounds (tens digit: 10->R1, 20->R2, etc.)
    from itertools import groupby
    team_rounds = []
    for tr_key, phases_in_tr in groupby(all_phase_nums, key=lambda p: p // 10):
        team_rounds.append((tr_key, list(phases_in_tr)))

    # Auto-compute rotations if not provided
    if day_rotations is None:
        day_rotations = _compute_day_rotations(len(team_rounds))

    # Build sequence: one global round per team-round.
    # Within each team-round, rotate events based on day_rotations.
    sequence: List[RankedMatch] = []
    rank = 1

    for global_round, (tr_key, phase_nums) in enumerate(team_rounds):
        rotation = day_rotations.get(global_round, 0)
        rotated_events = _rotate_events(events_sorted, rotation)

        for phase_num in phase_nums:
            for e in rotated_events:
                phase_data = event_phases[e.id].get(phase_num)
                if not phase_data:
                    continue
                match_type, round_index, round_matches = phase_data
                label = _round_label(match_type, round_index)
                for m in round_matches:
                    sequence.append(RankedMatch(
                        rank=rank,
                        match_id=m.id,
                        match_code=m.match_code or "",
                        event_id=e.id,
                        event_name=e.name,
                        match_type=match_type,
                        round_index=round_index,
                        round_label=label,
                        matches_in_round=len(round_matches),
                        global_round=global_round,
                    ))
                    rank += 1

    return sequence


# ══════════════════════════════════════════════════════════════════════════
#  Slot Placement
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class DaySchedule:
    """Result of placing matches into one day."""
    day_date: object            # date
    matches_placed: int = 0
    total_slots: int = 0
    usable_slots: int = 0
    spare_slots: int = 0
    time_slot_summary: List[dict] = field(default_factory=list)


def place_matches_into_slots(
    session: Session,
    schedule_version_id: int,
) -> Tuple[List[DaySchedule], str]:
    """
    Place all matches into slots using the master sequence.

    Rules:
      1. All courts used (spare court reservation disabled)
      2. Fill matches in master-sequence rank order until day is full
      3. Next day picks up where previous day stopped
      4. Event rotation: Day 1 starts with event A, Day 2 with B, Day 3 with C

    Returns (day_summaries, full_output_text).
    """
    from app.models import ScheduleSlot

    # ── Load slots grouped by day and time ───────────────────────────
    all_slots = session.exec(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_version_id == schedule_version_id,
            ScheduleSlot.is_active == True,
        )
    ).all()

    # Group by day
    slots_by_day: Dict[object, List] = defaultdict(list)
    for s in all_slots:
        slots_by_day[s.day_date].append(s)
    sorted_days = sorted(slots_by_day.keys())

    # Compute usable slots per day
    day_usable: List[Tuple[object, int, List[Tuple]]] = []
    for day in sorted_days:
        day_slots = slots_by_day[day]
        by_time: Dict = defaultdict(list)
        for s in day_slots:
            by_time[s.start_time].append(s)
        sorted_times = sorted(by_time.keys())

        usable = 0
        time_info = []
        for i, t in enumerate(sorted_times):
            total_courts = len(by_time[t])
            reserve = 0  # spare court reservation disabled — use all courts
            available = total_courts - reserve
            usable += available
            time_info.append((t, total_courts, reserve, available))
        day_usable.append((day, usable, time_info))

    # ── Build master sequence (auto-computes rotations) ────────────
    seq = build_master_sequence(session, schedule_version_id, None)

    # ── Dynamic day-round boundaries ─────────────────────────────────
    # Discover team-rounds from the sequence, pair 2 per day.
    num_days = len(sorted_days)
    team_round_indices = sorted(set(rm.global_round for rm in seq))
    num_team_rounds = len(team_round_indices)
    day_round_groups = _build_day_round_groups(num_team_rounds, num_days)

    # Split sequence into per-day pools based on global_round.
    day_pools: List[List[RankedMatch]] = [[] for _ in range(num_days)]
    for rm in seq:
        for di, rg in enumerate(day_round_groups):
            if rm.global_round in rg:
                day_pools[di].append(rm)
                break
        else:
            day_pools[-1].append(rm)

    # ── Place matches day by day ─────────────────────────────────────
    results: List[DaySchedule] = []
    lines: List[str] = []
    overflow: List[RankedMatch] = []  # matches that didn't fit previous day

    for day_idx, (day, usable, time_info) in enumerate(day_usable):
        ds = DaySchedule(
            day_date=day,
            total_slots=sum(ti[1] for ti in time_info),
            usable_slots=usable,
        )

        lines.append(f"\n{'='*80}")
        lines.append(f"Day {day_idx + 1}: {day}  ({usable} usable slots)")
        lines.append(f"{'='*80}")
        for t, total, reserve, available in time_info:
            lines.append(f"  {t}:  {total} courts - {reserve} reserved = {available} usable")
        lines.append("")

        # This day's match pool: overflow first, then assigned rounds
        pool: List[RankedMatch] = list(overflow)
        if day_idx < len(day_pools):
            pool.extend(day_pools[day_idx])
        overflow = []

        # Fill this day from pool
        placed = 0
        placed_by_time: Dict = defaultdict(list)
        time_capacity = {t: avail for t, _, _, avail in time_info}
        time_order = [t for t, _, _, _ in time_info]
        time_cursor = 0
        time_used = defaultdict(int)
        pool_idx = 0

        while pool_idx < len(pool) and placed < usable:
            # Find next time slot with capacity
            while time_cursor < len(time_order):
                t = time_order[time_cursor]
                if time_used[t] < time_capacity[t]:
                    break
                time_cursor += 1
            if time_cursor >= len(time_order):
                break  # day is full

            t = time_order[time_cursor]
            rm = pool[pool_idx]
            placed_by_time[t].append(rm)
            time_used[t] += 1
            placed += 1
            pool_idx += 1

        # Anything left in pool becomes overflow for next day
        overflow = pool[pool_idx:]

        ds.matches_placed = placed
        ds.spare_slots = usable - placed

        # Print day schedule
        for t, _, _, available in time_info:
            matches_at_t = placed_by_time.get(t, [])
            # Summarize by event + stage
            summary: Dict[str, int] = defaultdict(int)
            for rm in matches_at_t:
                summary[f"{rm.event_name} {rm.round_label}"] += 1
            spare = available - len(matches_at_t)
            lines.append(f"  {t} -- {available} courts ({len(matches_at_t)} assigned, {spare} spare)")
            for desc, cnt in summary.items():
                lines.append(f"      {desc}: {cnt}")

        lines.append(f"\n  Day total: {placed} placed, {ds.spare_slots} spare")
        results.append(ds)

    # Unplaced?
    unplaced = len(overflow)
    if unplaced > 0:
        lines.append(f"\nWARNING: {unplaced} matches could not be placed!")
    else:
        lines.append(f"\nAll {len(seq)} matches placed successfully.")

    return results, "\n".join(lines)


def _build_day_round_groups(
    num_team_rounds: int,
    num_days: int,
) -> List[set]:
    """
    Dynamically assign team-rounds to tournament days.

    Rule: 2 team-rounds per day (max 2 matches per team per day).
    If there are more days than needed, extra days get no assigned rounds
    but can still receive overflow.

    Examples:
        3 rounds, 2 days  -> [{0,1}, {2}]
        5 rounds, 3 days  -> [{0,1}, {2,3}, {4}]
        5 rounds, 4 days  -> [{0,1}, {2,3}, {4}, set()]
        4 rounds, 2 days  -> [{0,1}, {2,3}]
        3 rounds, 3 days  -> [{0,1}, {2}, set()]
    """
    groups: List[set] = [set() for _ in range(num_days)]
    for tr in range(num_team_rounds):
        day_idx = min(tr // 2, num_days - 1)  # cap to last day
        groups[day_idx].add(tr)
    return groups


def run_sequence_schedule(
    session: Session,
    tournament_id: int,
    schedule_version_id: int,
    *,
    locked_match_ids: Optional[Set[int]] = None,
    blocked_slot_ids: Optional[Set[int]] = None,
) -> object:
    """
    Master-sequence scheduler: build the ranked match list, then assign
    each match to a concrete ScheduleSlot, creating MatchAssignment rows.

    Fully generic — works for any number of events, any size, any number
    of tournament days (2, 3, or 4).

    locked_match_ids: matches already pre-assigned via MatchLock — skip them.
    blocked_slot_ids: slots that are blocked or occupied by locked assignments
        — exclude from the available pool.

    Returns an object whose attributes match what the route handler expects:
        .total_assigned, .total_failed, .total_reserved_spares,
        .duration_ms, .day_results (list of dicts)

    Rules applied:
      1. All courts used (spare court reservation disabled)
      2. Matches filled in master-sequence rank order
      3. No team plays more than 2 matches per day (enforced by pairing
         2 team-rounds per day; overflow carries to next day)
      4. Event rotation: each day starts with a different event from
         the largest tied-team-count group
    """
    import time as _time
    from datetime import datetime
    from app.models import ScheduleSlot, MatchAssignment

    t0 = _time.monotonic()

    _locked = locked_match_ids or set()
    _blocked = blocked_slot_ids or set()

    # ── Load all active slots (excluding blocked) ──────────────────
    all_slots = [
        s for s in session.exec(
            select(ScheduleSlot).where(
                ScheduleSlot.schedule_version_id == schedule_version_id,
                ScheduleSlot.is_active == True,
            )
        ).all()
        if s.id not in _blocked
    ]

    # Group slots: day -> time -> list of ScheduleSlot (sorted by court)
    slots_by_day: Dict[object, Dict[object, List]] = defaultdict(lambda: defaultdict(list))
    for s in all_slots:
        slots_by_day[s.day_date][s.start_time].append(s)
    for day in slots_by_day:
        for t in slots_by_day[day]:
            slots_by_day[day][t].sort(key=lambda s: s.court_number)
    sorted_days = sorted(slots_by_day.keys())
    num_days = len(sorted_days)

    # Build per-day info: list of (day, usable, time_details)
    # time_details = list of (time, total, reserve, available, [usable_slots])
    day_info_list = []
    for day in sorted_days:
        sorted_times = sorted(slots_by_day[day].keys())
        time_details = []
        usable = 0
        for i, t in enumerate(sorted_times):
            court_slots = slots_by_day[day][t]
            total = len(court_slots)
            reserve = 0  # spare court reservation disabled — use all courts
            available = total - reserve
            usable_slots = court_slots[:available]
            usable += available
            time_details.append((t, total, reserve, available, usable_slots))
        day_info_list.append((day, usable, time_details))

    # ── Build master sequence (auto-computes rotations) ──────────────
    # Pass None so build_master_sequence discovers team-rounds from
    # the match data and auto-computes rotations.
    seq = build_master_sequence(session, schedule_version_id, None)

    # Remove locked matches — they are already pre-assigned
    if _locked:
        seq = [rm for rm in seq if rm.match_id not in _locked]

    if not seq:
        class _Empty:
            pass
        r = _Empty()
        r.total_assigned = 0
        r.total_failed = 0
        r.total_reserved_spares = 0
        r.duration_ms = 0
        r.day_results = []
        return r

    # ── Discover team-rounds and build day-round boundaries ──────────
    team_round_indices = sorted(set(rm.global_round for rm in seq))
    num_team_rounds = len(team_round_indices)

    day_round_groups = _build_day_round_groups(num_team_rounds, num_days)

    # Split sequence into per-day pools based on global_round
    day_pools: List[List[RankedMatch]] = [[] for _ in range(num_days)]
    for rm in seq:
        for di, rg in enumerate(day_round_groups):
            if rm.global_round in rg:
                day_pools[di].append(rm)
                break
        else:
            # Round not assigned to any day — put on last day
            day_pools[-1].append(rm)

    # ── Place matches and create MatchAssignment records ─────────────
    total_assigned = 0
    total_failed = 0
    total_reserved = 0
    day_results = []
    overflow: List[RankedMatch] = []

    for day_idx, (day, usable, time_details) in enumerate(day_info_list):
        day_t0 = _time.monotonic()

        # This day's pool: overflow first, then assigned rounds
        pool: List[RankedMatch] = list(overflow)
        if day_idx < len(day_pools):
            pool.extend(day_pools[day_idx])
        overflow = []

        # Count reserved spares for this day
        day_reserved = sum(td[2] for td in time_details)
        total_reserved += day_reserved

        # Build a flat list of available slot records for this day
        # (ordered by time, then by court within each time)
        slot_queue: List[ScheduleSlot] = []
        for t, total, reserve, available, usable_slots in time_details:
            slot_queue.extend(usable_slots)

        # Assign matches to slots
        placed = 0
        slot_cursor = 0
        batch_summary: Dict[str, int] = defaultdict(int)
        pool_idx = 0

        while pool_idx < len(pool) and slot_cursor < len(slot_queue):
            slot = slot_queue[slot_cursor]
            rm = pool[pool_idx]

            assignment = MatchAssignment(
                schedule_version_id=schedule_version_id,
                match_id=rm.match_id,
                slot_id=slot.id,
                assigned_at=datetime.utcnow(),
                assigned_by="SEQUENCE_V1",
            )
            session.add(assignment)
            batch_summary[f"{rm.event_name} {rm.round_label}"] += 1
            placed += 1
            slot_cursor += 1
            pool_idx += 1

        # Leftover goes to next day
        overflow = pool[pool_idx:]
        failed = len(overflow) if day_idx == len(day_info_list) - 1 else 0

        total_assigned += placed
        day_ms = int((_time.monotonic() - day_t0) * 1000)

        # Build batch info for response (one entry per event+stage group)
        batches = [
            {"label": label, "assigned": cnt, "failed": 0}
            for label, cnt in batch_summary.items()
        ]

        day_results.append({
            "day": str(day),
            "assigned": placed,
            "failed": failed,
            "reserved_spares": day_reserved,
            "duration_ms": day_ms,
            "batches": batches,
        })

    # Handle any final overflow as failures
    if overflow:
        total_failed = len(overflow)

    session.flush()

    elapsed_ms = int((_time.monotonic() - t0) * 1000)

    # Return result object matching FullPolicyRunResponse expectations
    class _Result:
        pass
    result = _Result()
    result.total_assigned = total_assigned
    result.total_failed = total_failed
    result.total_reserved_spares = total_reserved
    result.duration_ms = elapsed_ms
    result.day_results = day_results
    return result


def print_sequence(sequence: List[RankedMatch]) -> str:
    """Format the sequence as a readable table string."""
    lines = []
    lines.append(f"{'Rank':<6} {'Event':<14} {'Stage':<14} {'Round':<14} {'Matches':<8} {'Match Code':<35} {'Match ID'}")
    lines.append("-" * 110)

    current_gr = -1
    for rm in sequence:
        if rm.global_round != current_gr:
            current_gr = rm.global_round
            lines.append(f"\n--- Global Round {current_gr + 1} ---")
        lines.append(
            f"{rm.rank:<6} {rm.event_name:<14} {rm.match_type:<14} {rm.round_label:<14} "
            f"{rm.matches_in_round:<8} {rm.match_code:<35} {rm.match_id}"
        )

    return "\n".join(lines)


# ── Standalone runner ────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from app.database import engine

    sv_id = int(sys.argv[1]) if len(sys.argv) > 1 else 4  # default to SV 4

    with Session(engine) as session:
        seq = build_master_sequence(session, sv_id)
        output = print_sequence(seq)
        print(output)

        # Also write to file
        outfile = f"master_sequence_sv{sv_id}.txt"
        with open(outfile, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\nWritten to {outfile} ({len(seq)} matches)")
