"""
Match generation utilities for Phase 3A
Uses the same logic as frontend drawEstimation.ts to ensure consistency
"""

from typing import Dict, List

from app.models.event import Event
from app.models.match import Match


def calculate_match_counts(template_type: str, team_count: int, wf_rounds: int, guarantee: int) -> Dict:
    """
    Calculate match counts for an event.
    Returns dict with: wf_matches, wf_rounds, standard_matches
    """
    if team_count % 2 != 0:
        raise ValueError(f"team_count must be even, got {team_count}")

    if template_type == "RR_ONLY":
        return {"wf_matches": 0, "wf_rounds": 0, "standard_matches": rr_matches(team_count)}

    elif template_type == "WF_TO_POOLS_4":
        if team_count % 4 != 0:
            raise ValueError(f"WF_TO_POOLS_4 requires team_count divisible by 4, got {team_count}")

        wf_matches = wf_round_matches(team_count) * wf_rounds
        pools = team_count / 4
        rr_matches_total = pools * rr_matches(4)  # 6 matches per pool
        placement_matches = team_count / 2

        if guarantee == 5:
            standard_matches = int(rr_matches_total + placement_matches)
        else:
            standard_matches = int(rr_matches_total)

        return {"wf_matches": int(wf_matches), "wf_rounds": wf_rounds, "standard_matches": standard_matches}

    elif template_type == "CANONICAL_32":
        # Now an 8-team bracket (renamed from historical 32-team)
        if team_count != 8:
            raise ValueError(f"CANONICAL_32 (8-team bracket) requires team_count=8, got {team_count}")
        if wf_rounds != 2:
            raise ValueError(f"CANONICAL_32 requires wf_rounds=2, got {wf_rounds}")

        wf_matches = wf_round_matches(8) * 2  # 8 matches (2 rounds of WF)

        # 8-team bracket structure:
        # MAIN: 7 (4 QF + 2 SF + 1 Final)
        # Guarantee 4: +2 CONSOLATION Tier 1 = 9 total
        # Guarantee 5: +2 Tier 1 + 1 Tier 2 + 3 PLACEMENT = 13 total
        if guarantee == 5:
            standard_matches = 13  # 7 MAIN + 2 CONS T1 + 1 CONS T2 + 3 PLACEMENT
        else:  # guarantee == 4
            standard_matches = 9  # 7 MAIN + 2 CONS T1

        return {"wf_matches": int(wf_matches), "wf_rounds": 2, "standard_matches": standard_matches}

    else:
        raise ValueError(f"Unknown template type: {template_type}")


def rr_matches(n: int) -> int:
    """Round robin match count: n * (n-1) / 2"""
    if n % 2 != 0:
        raise ValueError(f"rr_matches: n must be even, got {n}")
    return (n * (n - 1)) // 2


def wf_round_matches(n: int) -> int:
    """Waterfall round match count: n / 2"""
    if n % 2 != 0:
        raise ValueError(f"wf_round_matches: n must be even, got {n}")
    return n // 2


def generate_wf_matches(
    event: Event,
    schedule_version_id: int,
    tournament_id: int,
    wf_rounds: int,
    duration_minutes: int,
    event_prefix: str,
    session=None,  # Optional: for WF grouping support
) -> List[Match]:
    """Generate waterfall matches for an event

    Match type: "WF"
    Round index: 1..wf_rounds (index within WF type)

    WF Grouping V1:
    If teams have wf_group_index assigned, generates WF matches within each group only.
    Each team in a size-4 group gets exactly 3 WF matches (round robin within group).
    Teams in different groups never play in WF.
    """
    from sqlmodel import select

    from app.models.team import Team

    matches = []

    # Check if WF grouping is active (teams have wf_group_index assigned)
    use_grouping = False
    groups = {}

    if session:
        # Load teams and check for grouping
        teams = session.exec(select(Team).where(Team.event_id == event.id)).all()

        # Check if any team has wf_group_index assigned
        if any(team.wf_group_index is not None for team in teams):
            use_grouping = True

            # Partition teams by wf_group_index
            for team in teams:
                if team.wf_group_index is not None:
                    if team.wf_group_index not in groups:
                        groups[team.wf_group_index] = []
                    groups[team.wf_group_index].append(team)

    if use_grouping and groups:
        # Generate WF matches within each group (round robin)
        match_num = 1

        for group_index in sorted(groups.keys()):
            group_teams = groups[group_index]
            len(group_teams)

            # Generate round robin matches within this group
            # For a size-4 group: 6 matches total (3 per team)
            # Spread across wf_rounds

            # Generate all pairs for this group
            all_pairs = []
            for i in range(len(group_teams)):
                for j in range(i + 1, len(group_teams)):
                    all_pairs.append((group_teams[i], group_teams[j]))

            # Distribute pairs across rounds
            matches_per_round = len(all_pairs) // wf_rounds
            remainder = len(all_pairs) % wf_rounds

            pair_idx = 0
            for round_num in range(1, wf_rounds + 1):
                # Calculate how many matches in this round
                matches_this_round = matches_per_round + (1 if round_num <= remainder else 0)

                for seq in range(1, matches_this_round + 1):
                    if pair_idx >= len(all_pairs):
                        break

                    team_a, team_b = all_pairs[pair_idx]
                    match_code = f"{event_prefix}_WF_G{group_index}_{round_num:02d}_{seq:02d}"

                    match = Match(
                        tournament_id=tournament_id,
                        event_id=event.id,
                        schedule_version_id=schedule_version_id,
                        match_code=match_code,
                        match_type="WF",
                        round_number=round_num,
                        round_index=round_num,
                        sequence_in_round=match_num,  # Global sequence
                        duration_minutes=duration_minutes,
                        placeholder_side_a=f"Team {team_a.id}",
                        placeholder_side_b=f"Team {team_b.id}",
                        status="unscheduled",
                    )
                    matches.append(match)
                    match_num += 1
                    pair_idx += 1

        return matches

    # Original logic (no grouping)
    match_num = 1

    for round_num in range(1, wf_rounds + 1):
        matches_in_round = wf_round_matches(event.team_count)

        for seq in range(1, matches_in_round + 1):
            match_code = f"{event_prefix}_WF_{round_num:02d}_{seq:02d}"

            match = Match(
                tournament_id=tournament_id,
                event_id=event.id,
                schedule_version_id=schedule_version_id,
                match_code=match_code,
                match_type="WF",
                round_number=round_num,
                round_index=round_num,  # Index within WF type (1..wf_rounds)
                sequence_in_round=seq,
                duration_minutes=duration_minutes,
                placeholder_side_a="TBD",
                placeholder_side_b="TBD",
                status="unscheduled",
            )
            matches.append(match)
            match_num += 1

    return matches


def generate_standard_matches(
    event: Event,
    schedule_version_id: int,
    tournament_id: int,
    count: int,
    duration_minutes: int,
    event_prefix: str,
    template_type: str,
) -> List[Match]:
    """Generate standard matches for an event"""
    matches = []

    # Determine match type based on template
    if template_type == "RR_ONLY":
        # Round Robin Only: match_type = "MAIN", round_index = RR round number
        teams = event.team_count
        total_rounds = teams - 1
        matches_per_round = teams // 2

        match_num = 1
        for round_num in range(1, total_rounds + 1):
            for seq in range(1, matches_per_round + 1):
                if match_num > count:
                    break
                match_code = f"{event_prefix}_RR_{round_num:02d}_{seq:02d}"
                match = Match(
                    tournament_id=tournament_id,
                    event_id=event.id,
                    schedule_version_id=schedule_version_id,
                    match_code=match_code,
                    match_type="MAIN",  # Normalized to MAIN
                    round_number=round_num,
                    round_index=round_num,  # Index within MAIN type (RR round number)
                    sequence_in_round=seq,
                    duration_minutes=duration_minutes,
                    placeholder_side_a="TBD",
                    placeholder_side_b="TBD",
                    status="unscheduled",
                )
                matches.append(match)
                match_num += 1
            if match_num > count:
                break

    elif template_type == "WF_TO_POOLS_4":
        # Post-waterfall matches: match_type = "MAIN", round_index = 1..N
        # Each pool round is a separate round_index
        pools = event.team_count // 4
        pool_rr_matches = 6  # rr_matches(4) = 6

        match_num = 1
        main_round_index = 1  # Index within MAIN type

        # Pool matches (post-waterfall, so MAIN type)
        # Each pool gets its own round_index
        for pool_num in range(1, pools + 1):
            for seq in range(1, pool_rr_matches + 1):
                if match_num > count:
                    break
                match_code = f"{event_prefix}_POOL{pool_num}_RR_{seq:02d}"
                match = Match(
                    tournament_id=tournament_id,
                    event_id=event.id,
                    schedule_version_id=schedule_version_id,
                    match_code=match_code,
                    match_type="MAIN",  # Normalized to MAIN
                    round_number=pool_num,  # Keep pool number for reference
                    round_index=main_round_index,  # Index within MAIN type (same for all matches in this pool)
                    sequence_in_round=seq,
                    duration_minutes=duration_minutes,
                    placeholder_side_a=f"Pool{pool_num} TBD",
                    placeholder_side_b=f"Pool{pool_num} TBD",
                    status="unscheduled",
                )
                matches.append(match)
                match_num += 1
            main_round_index += 1  # Next pool gets next round_index

        # Placement matches (if guarantee 5) - also MAIN type, separate round_index
        placement_count = event.team_count // 2
        if match_num <= count:
            for seq in range(1, placement_count + 1):
                if match_num > count:
                    break
                match_code = f"{event_prefix}_PLACE_{seq:02d}"
                match = Match(
                    tournament_id=tournament_id,
                    event_id=event.id,
                    schedule_version_id=schedule_version_id,
                    match_code=match_code,
                    match_type="MAIN",  # Normalized to MAIN
                    round_number=main_round_index,  # Keep for reference
                    round_index=main_round_index,  # Index within MAIN type
                    sequence_in_round=seq,
                    duration_minutes=duration_minutes,
                    placeholder_side_a="TBD",
                    placeholder_side_b="TBD",
                    status="unscheduled",
                )
                matches.append(match)
                match_num += 1
            main_round_index += 1

    elif template_type == "CANONICAL_32":
        # 8-team bracket: QF (4) + SF (2) + Final (1) = 7 MAIN matches
        # Generate in order: Round 1 (QF), Round 2 (SF), Round 3 (Final)

        # Round 1: Quarterfinals (4 matches)
        for seq in range(1, 5):
            match_code = f"{event_prefix}_QF{seq}"
            match = Match(
                tournament_id=tournament_id,
                event_id=event.id,
                schedule_version_id=schedule_version_id,
                match_code=match_code,
                match_type="MAIN",
                round_number=1,
                round_index=1,
                sequence_in_round=seq,
                duration_minutes=duration_minutes,
                placeholder_side_a="TBD",
                placeholder_side_b="TBD",
                status="unscheduled",
            )
            matches.append(match)

        # Round 2: Semifinals (2 matches)
        for seq in range(1, 3):
            match_code = f"{event_prefix}_SF{seq}"
            match = Match(
                tournament_id=tournament_id,
                event_id=event.id,
                schedule_version_id=schedule_version_id,
                match_code=match_code,
                match_type="MAIN",
                round_number=2,
                round_index=2,
                sequence_in_round=seq,
                duration_minutes=duration_minutes,
                placeholder_side_a="TBD",
                placeholder_side_b="TBD",
                status="unscheduled",
            )
            matches.append(match)

        # Round 3: Final (1 match)
        match_code = f"{event_prefix}_FINAL"
        match = Match(
            tournament_id=tournament_id,
            event_id=event.id,
            schedule_version_id=schedule_version_id,
            match_code=match_code,
            match_type="MAIN",
            round_number=3,
            round_index=3,
            sequence_in_round=1,
            duration_minutes=duration_minutes,
            placeholder_side_a="TBD",
            placeholder_side_b="TBD",
            status="unscheduled",
        )
        matches.append(match)

    else:
        # Fallback: simple sequential matches - treat as MAIN
        for seq in range(1, count + 1):
            match_code = f"{event_prefix}_STD_{seq:02d}"
            match = Match(
                tournament_id=tournament_id,
                event_id=event.id,
                schedule_version_id=schedule_version_id,
                match_code=match_code,
                match_type="MAIN",  # Normalized to MAIN
                round_number=1,
                round_index=1,  # Index within MAIN type
                sequence_in_round=seq,
                duration_minutes=duration_minutes,
                placeholder_side_a="TBD",
                placeholder_side_b="TBD",
                status="unscheduled",
            )
            matches.append(match)

    return matches


def generate_consolation_matches(
    event: Event, schedule_version_id: int, tournament_id: int, duration_minutes: int, event_prefix: str, guarantee: int
) -> List[Match]:
    """
    Generate consolation matches for 8-team bracket events.

    Tier 1: First-round losers (2 matches) - always generated
    Tier 2: Second consolation (1 match) - only if guarantee == 5

    Args:
        event: The event to generate consolation for
        schedule_version_id: Schedule version ID
        tournament_id: Tournament ID
        duration_minutes: Match duration in minutes
        event_prefix: Event prefix for match codes
        guarantee: Guarantee level (4 or 5)

    Returns:
        List of consolation matches
    """
    matches = []

    # Tier 1: First-round losers (2 matches, always generated for 8-team bracket)
    for seq in range(1, 3):
        match_code = f"{event_prefix}_CONS1_{seq}"
        match = Match(
            tournament_id=tournament_id,
            event_id=event.id,
            schedule_version_id=schedule_version_id,
            match_code=match_code,
            match_type="CONSOLATION",
            round_number=1,
            round_index=1,  # Tier 1 consolation round
            sequence_in_round=seq,
            duration_minutes=duration_minutes,
            consolation_tier=1,
            placeholder_side_a="TBD",
            placeholder_side_b="TBD",
            status="unscheduled",
        )
        matches.append(match)

    # Tier 2: Second consolation (1 match, only if guarantee == 5)
    if guarantee == 5:
        match_code = f"{event_prefix}_CONS2_1"
        match = Match(
            tournament_id=tournament_id,
            event_id=event.id,
            schedule_version_id=schedule_version_id,
            match_code=match_code,
            match_type="CONSOLATION",
            round_number=2,
            round_index=2,  # Tier 2 consolation round
            sequence_in_round=1,
            duration_minutes=duration_minutes,
            consolation_tier=2,
            placeholder_side_a="TBD",
            placeholder_side_b="TBD",
            status="unscheduled",
        )
        matches.append(match)

    return matches


def generate_placement_matches(
    event: Event, schedule_version_id: int, tournament_id: int, duration_minutes: int, event_prefix: str
) -> List[Match]:
    """
    Generate post-final placement matches for 8-team bracket (Guarantee 5 only).

    3 matches total:
    - 1x MAIN_SF_LOSERS (3rd/4th place)
    - 1x CONS_R1_WINNERS (5th/6th place from consolation winners)
    - 1x CONS_R1_LOSERS (7th/8th place from consolation losers)

    Args:
        event: The event to generate placement for
        schedule_version_id: Schedule version ID
        tournament_id: Tournament ID
        duration_minutes: Match duration in minutes
        event_prefix: Event prefix for match codes

    Returns:
        List of placement matches
    """
    matches = []

    placement_types = [("MAIN_SF_LOSERS", "3rd/4th"), ("CONS_R1_WINNERS", "5th/6th"), ("CONS_R1_LOSERS", "7th/8th")]

    for seq, (placement_type, label) in enumerate(placement_types, start=1):
        match_code = f"{event_prefix}_PL{seq}_{label.replace('/', '')}"
        match = Match(
            tournament_id=tournament_id,
            event_id=event.id,
            schedule_version_id=schedule_version_id,
            match_code=match_code,
            match_type="PLACEMENT",
            round_number=1,
            round_index=1,  # All placement in round 1
            sequence_in_round=seq,
            duration_minutes=duration_minutes,
            placement_type=placement_type,
            placeholder_side_a="TBD",
            placeholder_side_b="TBD",
            status="unscheduled",
        )
        matches.append(match)

    return matches
