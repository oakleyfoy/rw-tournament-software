"""
Match generation utilities for Phase 3A
Uses the same logic as frontend drawEstimation.ts to ensure consistency
"""

from typing import Dict, List, Optional, Tuple

from app.models.event import Event
from app.models.match import Match


def _rr_pairs_circle(teams: List) -> List[Tuple[int, int, object, object]]:
    """
    Round-robin pairings via circle method. Returns list of (round_1based, seq_1based, team_a, team_b).
    teams: list of Team (or any) in deterministic order (e.g. by seed).
    """
    n = len(teams)
    if n % 2 != 0:
        raise ValueError(f"Round-robin requires even team count, got {n}")
    # Circle: position 0 fixed, others rotate. Round r: (0,n-1), (1,n-2), ...
    half = n // 2
    result = []
    # positions 0..n-1; round r: pos[i] vs pos[n-1-i]
    positions = list(range(n))
    for round_num in range(1, n):  # n-1 rounds
        for seq in range(1, half + 1):
            i, j = seq - 1, n - seq
            team_a, team_b = teams[positions[i]], teams[positions[j]]
            result.append((round_num, seq, team_a, team_b))
        # Rotate: keep 0, then positions[1] becomes last, positions[2] becomes 1, ...
        positions = [positions[0]] + [positions[-1]] + positions[1:-1]
    return result


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

        # Canonical inventory: 16 teams, 2 WF rounds, guarantee 5 → 8 WF R1 + 8 WF R2 + 24 pool RR = 40
        if team_count == 16 and wf_rounds == 2:
            wf_matches = 16  # 8 R1 + 8 R2
            standard_matches = 24  # 4 pools × 6 RR (no placement in canonical 40)
            return {"wf_matches": wf_matches, "wf_rounds": wf_rounds, "standard_matches": standard_matches}

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


def generate_wf_to_pools_4_canonical_r1(
    event: Event,
    schedule_version_id: int,
    tournament_id: int,
    duration_minutes: int,
    event_prefix: str,
    session=None,
    effective_team_count: Optional[int] = None,
) -> List[Match]:
    """
    Canonical WF R1 for WF_TO_POOLS_4 (16 teams, 2 rounds): 8 matches.
    Pair seed order: 1v16, 2v15, 3v14, 4v13, 5v12, 6v11, 7v10, 8v9.
    stage=WF, wf_round=1, round_index=1, sequence_in_round=1..8.
    """
    matches = []
    linked_teams = []
    if session and (effective_team_count or event.team_count) >= 16:
        from app.utils.team_injection import get_deterministic_teams
        linked_teams = get_deterministic_teams(session, event.id) or []
    bind_teams = len(linked_teams) == 16
    # R1 pairs: (0,15), (1,14), (2,13), (3,12), (4,11), (5,10), (6,9), (7,8) (0-based seed 1..16)
    pairs = [(i, 15 - i) for i in range(8)]
    for seq, (a_idx, b_idx) in enumerate(pairs, 1):
        team_a_id = team_b_id = None
        placeholder_a = "Seed {} Team".format(a_idx + 1)
        placeholder_b = "Seed {} Team".format(b_idx + 1)
        if bind_teams:
            team_a_id = linked_teams[a_idx].id
            team_b_id = linked_teams[b_idx].id
            placeholder_a = linked_teams[a_idx].name or placeholder_a
            placeholder_b = linked_teams[b_idx].name or placeholder_b
        match_code = f"{event_prefix}_WF_01_{seq:02d}"
        match = Match(
            tournament_id=tournament_id,
            event_id=event.id,
            schedule_version_id=schedule_version_id,
            match_code=match_code,
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=seq,
            duration_minutes=duration_minutes,
            placeholder_side_a=placeholder_a,
            placeholder_side_b=placeholder_b,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            status="unscheduled",
        )
        matches.append(match)
    return matches


def generate_wf_to_pools_4_canonical_r2(
    event: Event,
    schedule_version_id: int,
    tournament_id: int,
    duration_minutes: int,
    event_prefix: str,
    r1_match_ids: List[int],
) -> List[Match]:
    """
    Canonical WF R2 for WF_TO_POOLS_4: 8 matches (4 winners bracket + 4 losers bracket).
    Winners: W(R1_1)vs W(R1_8), W(R1_2)vs W(R1_7), W(R1_3)vs W(R1_6), W(R1_4)vs W(R1_5).
    Losers:  L(R1_1)vs L(R1_8), L(R1_2)vs L(R1_7), L(R1_3)vs L(R1_6), L(R1_4)vs L(R1_5).
    team_a_id/team_b_id = None; source_match_* and source_*_role set.
    """
    if len(r1_match_ids) != 8:
        raise ValueError(f"Canonical WF R2 requires 8 R1 match ids, got {len(r1_match_ids)}")
    matches = []
    # Winners bracket: seq 1..4
    w_pairs = [(0, 7), (1, 6), (2, 5), (3, 4)]  # R1 0-indexed
    for seq, (i, j) in enumerate(w_pairs, 1):
        match_code = f"{event_prefix}_WF_02_{seq:02d}"
        match = Match(
            tournament_id=tournament_id,
            event_id=event.id,
            schedule_version_id=schedule_version_id,
            match_code=match_code,
            match_type="WF",
            round_number=2,
            round_index=2,
            sequence_in_round=seq,
            duration_minutes=duration_minutes,
            placeholder_side_a=f"W(R1_{i+1})",
            placeholder_side_b=f"W(R1_{j+1})",
            team_a_id=None,
            team_b_id=None,
            status="unscheduled",
            source_match_a_id=r1_match_ids[i],
            source_match_b_id=r1_match_ids[j],
            source_a_role="WINNER",
            source_b_role="WINNER",
        )
        matches.append(match)
    # Losers bracket: seq 5..8
    for seq, (i, j) in enumerate(w_pairs, 5):
        match_code = f"{event_prefix}_WF_02_{seq:02d}"
        match = Match(
            tournament_id=tournament_id,
            event_id=event.id,
            schedule_version_id=schedule_version_id,
            match_code=match_code,
            match_type="WF",
            round_number=2,
            round_index=2,
            sequence_in_round=seq,
            duration_minutes=duration_minutes,
            placeholder_side_a=f"L(R1_{i+1})",
            placeholder_side_b=f"L(R1_{j+1})",
            team_a_id=None,
            team_b_id=None,
            status="unscheduled",
            source_match_a_id=r1_match_ids[i],
            source_match_b_id=r1_match_ids[j],
            source_a_role="LOSER",
            source_b_role="LOSER",
        )
        matches.append(match)
    return matches


def generate_wf_matches(
    event: Event,
    schedule_version_id: int,
    tournament_id: int,
    wf_rounds: int,
    duration_minutes: int,
    event_prefix: str,
    session=None,  # Optional: for WF grouping support
    effective_team_count: Optional[int] = None,
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
                        placeholder_side_a=team_a.name or f"Team {team_a.id}",
                        placeholder_side_b=team_b.name or f"Team {team_b.id}",
                        team_a_id=team_a.id,
                        team_b_id=team_b.id,
                        status="unscheduled",
                    )
                    matches.append(match)
                    match_num += 1
                    pair_idx += 1

        return matches

    # Original logic (no grouping). Use event.team_count for structure (how many matches); use effective_team_count for binding.
    n_teams_structure = event.team_count  # number of WF match slots (e.g. 16 for 16-team draw)
    n_teams_binding = effective_team_count if effective_team_count is not None else event.team_count
    linked_teams_for_wf = []
    if session and n_teams_binding >= 2:
        from app.utils.team_injection import get_deterministic_teams
        linked_teams_for_wf = get_deterministic_teams(session, event.id) or []
    bind_wf = len(linked_teams_for_wf) == n_teams_binding and n_teams_binding % 2 == 0
    wf_pairs_by_round = []
    if bind_wf:
        # Circle method: round r uses positions rotated (r-1) times; pairs (pos[0],pos[n-1]), (pos[1],pos[n-2]), ...
        half = n_teams_binding // 2
        for r in range(1, wf_rounds + 1):
            positions = list(range(n_teams_binding))
            for _ in range(r - 1):
                positions = [positions[0]] + [positions[-1]] + positions[1:-1]
            round_pairs = []
            for seq in range(half):
                round_pairs.append((linked_teams_for_wf[positions[seq]], linked_teams_for_wf[positions[n_teams_binding - 1 - seq]]))
            wf_pairs_by_round.append(round_pairs)

    match_num = 1
    for round_num in range(1, wf_rounds + 1):
        matches_in_round = wf_round_matches(n_teams_structure)

        for seq in range(1, matches_in_round + 1):
            match_code = f"{event_prefix}_WF_{round_num:02d}_{seq:02d}"
            team_a_id = team_b_id = None
            placeholder_a = placeholder_b = "TBD"
            if bind_wf and round_num <= len(wf_pairs_by_round):
                round_pairs = wf_pairs_by_round[round_num - 1]
                if seq - 1 < len(round_pairs):
                    ta, tb = round_pairs[seq - 1]
                    team_a_id, team_b_id = ta.id, tb.id
                    placeholder_a = ta.name or f"Team {ta.id}"
                    placeholder_b = tb.name or f"Team {tb.id}"
            match = Match(
                tournament_id=tournament_id,
                event_id=event.id,
                schedule_version_id=schedule_version_id,
                match_code=match_code,
                match_type="WF",
                round_number=round_num,
                round_index=round_num,
                sequence_in_round=seq,
                duration_minutes=duration_minutes,
                placeholder_side_a=placeholder_a,
                placeholder_side_b=placeholder_b,
                team_a_id=team_a_id,
                team_b_id=team_b_id,
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
    session=None,
    effective_team_count: Optional[int] = None,
) -> List[Match]:
    """Generate standard matches for an event. If session is provided and event has linked teams, bind team_a_id/team_b_id.
    Structure (how many matches/pools) uses event.team_count; binding uses effective_team_count when set.
    """
    matches = []
    # Structure = full draw size (e.g. 16 teams => 4 pools, 24 RR matches for WF_TO_POOLS_4)
    teams_config_structure = event.team_count
    teams_config_binding = effective_team_count if effective_team_count is not None else event.team_count

    # Load linked teams if session provided (for binding)
    linked_teams_ordered = []
    if session:
        from sqlmodel import select
        from app.models.team import Team
        from app.utils.team_injection import get_deterministic_teams
        linked_teams_ordered = get_deterministic_teams(session, event.id) or []

    # Determine match type based on template
    if template_type == "RR_ONLY":
        # Round Robin Only: match_type = "MAIN", round_index = RR round number
        total_rounds = teams_config_structure - 1
        matches_per_round = teams_config_structure // 2

        # If we have linked teams matching binding config, bind team ids
        bind_teams = len(linked_teams_ordered) == teams_config_binding and teams_config_binding >= 2
        rr_pairs = _rr_pairs_circle(linked_teams_ordered) if bind_teams else []
        pair_idx = 0

        match_num = 1
        for round_num in range(1, total_rounds + 1):
            for seq in range(1, matches_per_round + 1):
                if match_num > count:
                    break
                match_code = f"{event_prefix}_RR_{round_num:02d}_{seq:02d}"
                team_a_id = team_b_id = None
                placeholder_a = placeholder_b = "TBD"
                if bind_teams and pair_idx < len(rr_pairs):
                    _, _, ta, tb = rr_pairs[pair_idx]
                    team_a_id, team_b_id = ta.id, tb.id
                    placeholder_a = ta.name or f"Team {ta.id}"
                    placeholder_b = tb.name or f"Team {tb.id}"
                    pair_idx += 1
                match = Match(
                    tournament_id=tournament_id,
                    event_id=event.id,
                    schedule_version_id=schedule_version_id,
                    match_code=match_code,
                    match_type="MAIN",  # Normalized to MAIN
                    round_number=round_num,
                    round_index=round_num,
                    sequence_in_round=seq,
                    duration_minutes=duration_minutes,
                    placeholder_side_a=placeholder_a,
                    placeholder_side_b=placeholder_b,
                    team_a_id=team_a_id,
                    team_b_id=team_b_id,
                    status="unscheduled",
                )
                matches.append(match)
                match_num += 1
            if match_num > count:
                break

    elif template_type == "WF_TO_POOLS_4":
        # Post-waterfall matches: match_type = "MAIN", round_index = 1..N
        # Each pool round is a separate round_index. Use structure team count for pool count (e.g. 16 => 4 pools).
        pools = teams_config_structure // 4
        pool_rr_matches = 6  # rr_matches(4) = 6
        # Canonical 4 pools: pool_id A/B/C/D (WW, WL, LW, LL)
        pool_labels = ["A", "B", "C", "D"][:pools] if pools <= 4 else [str(i) for i in range(1, pools + 1)]

        # Partition linked teams by wf_group_index for pool RR binding; if no wf_group_index, split by index (first 4 = pool 1, next 4 = pool 2)
        pool_teams_by_num = {}
        if linked_teams_ordered:
            has_wf_index = any(getattr(t, "wf_group_index", None) is not None for t in linked_teams_ordered)
            if has_wf_index:
                pool_teams = {}
                for t in linked_teams_ordered:
                    idx = getattr(t, "wf_group_index", None)
                    if idx is not None:
                        if idx not in pool_teams:
                            pool_teams[idx] = []
                        pool_teams[idx].append(t)
                sorted_group_indices = sorted(pool_teams.keys())
                pool_teams_by_num = {i + 1: pool_teams[g] for i, g in enumerate(sorted_group_indices)}
            else:
                # No wf_group_index: partition by index (4 teams per pool)
                pool_size = 4
                for i in range(0, len(linked_teams_ordered), pool_size):
                    pool_num = (i // pool_size) + 1
                    pool_teams_by_num[pool_num] = linked_teams_ordered[i : i + pool_size]

        match_num = 1
        main_round_index = 1

        for pool_num in range(1, pools + 1):
            pool_label = pool_labels[pool_num - 1] if pool_num <= len(pool_labels) else str(pool_num)
            pool_team_list = (pool_teams_by_num.get(pool_num) or []) if linked_teams_ordered else []
            bind_pool = len(pool_team_list) == 4
            pool_pairs = _rr_pairs_circle(pool_team_list) if bind_pool else []
            pair_idx = 0

            for seq in range(1, pool_rr_matches + 1):
                if match_num > count:
                    break
                match_code = f"{event_prefix}_POOL{pool_label}_RR_{seq:02d}"
                team_a_id = team_b_id = None
                placeholder_a = placeholder_b = f"Pool {pool_label} TBD"
                if bind_pool and pair_idx < len(pool_pairs):
                    _, _, ta, tb = pool_pairs[pair_idx]
                    team_a_id, team_b_id = ta.id, tb.id
                    placeholder_a = ta.name or f"Team {ta.id}"
                    placeholder_b = tb.name or f"Team {tb.id}"
                    pair_idx += 1
                match = Match(
                    tournament_id=tournament_id,
                    event_id=event.id,
                    schedule_version_id=schedule_version_id,
                    match_code=match_code,
                    match_type="MAIN",
                    round_number=pool_num,
                    round_index=main_round_index,
                    sequence_in_round=seq,
                    duration_minutes=duration_minutes,
                    placeholder_side_a=placeholder_a,
                    placeholder_side_b=placeholder_b,
                    team_a_id=team_a_id,
                    team_b_id=team_b_id,
                    status="unscheduled",
                )
                matches.append(match)
                match_num += 1
            main_round_index += 1

        # Placement matches (if guarantee 5). Bind deterministically when we have linked teams so gate passes.
        placement_count = teams_config_structure // 2
        if match_num <= count:
            # Deterministic placement pairing when we have enough linked teams (e.g. 8 teams -> 4 placement matches)
            placement_pairs = []
            if len(linked_teams_ordered) >= placement_count * 2:
                for i in range(placement_count):
                    placement_pairs.append(
                        (linked_teams_ordered[i * 2], linked_teams_ordered[i * 2 + 1])
                    )
            for seq in range(1, placement_count + 1):
                if match_num > count:
                    break
                match_code = f"{event_prefix}_PLACE_{seq:02d}"
                team_a_id = team_b_id = None
                placeholder_a = placeholder_b = "TBD"
                if seq - 1 < len(placement_pairs):
                    ta, tb = placement_pairs[seq - 1]
                    team_a_id, team_b_id = ta.id, tb.id
                    placeholder_a = ta.name or f"Team {ta.id}"
                    placeholder_b = tb.name or f"Team {tb.id}"
                match = Match(
                    tournament_id=tournament_id,
                    event_id=event.id,
                    schedule_version_id=schedule_version_id,
                    match_code=match_code,
                    match_type="MAIN",
                    round_number=main_round_index,
                    round_index=main_round_index,
                    sequence_in_round=seq,
                    duration_minutes=duration_minutes,
                    placeholder_side_a=placeholder_a,
                    placeholder_side_b=placeholder_b,
                    team_a_id=team_a_id,
                    team_b_id=team_b_id,
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
