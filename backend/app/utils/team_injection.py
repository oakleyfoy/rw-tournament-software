"""
Team Injection V1 Logic
Deterministically assigns team IDs to matches based on seeding.
"""

import json
from datetime import datetime
from typing import List

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.team import Team


class TeamInjectionError(Exception):
    """Raised when team injection cannot proceed"""

    pass


def get_deterministic_teams(session: Session, event_id: int) -> List[Team]:
    """
    Get teams in deterministic order for injection.

    Order:
    1. seed ascending (non-null first)
    2. rating descending (non-null first)
    3. registration_timestamp ascending (non-null first)
    4. id ascending

    Returns:
        List of Team objects in deterministic order
    """
    query = select(Team).where(Team.event_id == event_id)
    teams = session.exec(query).all()

    def sort_key(team: Team):
        return (
            # seed: nulls last, ascending
            (team.seed is None, team.seed if team.seed is not None else 0),
            # rating: nulls last, descending (negate for desc)
            (team.rating is None, -(team.rating if team.rating is not None else 0)),
            # registration_timestamp: nulls last, ascending
            (
                team.registration_timestamp is None,
                team.registration_timestamp if team.registration_timestamp is not None else datetime.max,
            ),
            # id: ascending
            team.id,
        )

    return sorted(teams, key=sort_key)


def inject_bracket_8_teams(session: Session, event_id: int, schedule_version_id: int, teams: List[Team]) -> int:
    """
    Inject 8 teams into bracket quarterfinals.

    QF assignments:
    - QF1: seed 1 vs seed 8
    - QF2: seed 4 vs seed 5
    - QF3: seed 3 vs seed 6
    - QF4: seed 2 vs seed 7

    Detection: Finds matches with match_code containing "QF" (CANONICAL_32 template)

    Args:
        session: Database session
        event_id: Event ID
        schedule_version_id: Schedule version ID
        teams: List of exactly 8 teams in deterministic order

    Returns:
        Number of matches updated

    Raises:
        TeamInjectionError: If cannot find exactly 4 QF matches
    """
    if len(teams) != 8:
        raise TeamInjectionError(f"Expected exactly 8 teams, got {len(teams)}")

    # Find quarterfinal matches by match_code pattern
    # CANONICAL_32 template creates matches with codes like: "EVENT_QF1", "EVENT_QF2", etc.
    query = select(Match).where(
        Match.event_id == event_id, Match.schedule_version_id == schedule_version_id, Match.match_type == "MAIN"
    )

    all_matches = session.exec(query).all()

    # Filter for QF matches (match_code contains "QF")
    qf_matches = [m for m in all_matches if "QF" in m.match_code]
    qf_matches.sort(key=lambda m: m.match_code)  # Sort by match_code for consistent ordering

    if len(qf_matches) != 4:
        raise TeamInjectionError(
            f"Cannot inject teams into bracket: Expected exactly 4 QF matches "
            f"(match_code contains 'QF'), found {len(qf_matches)}. "
            f"This event may not be using the CANONICAL_32 (8-team bracket) template. "
            f"Current template may be pool play or round robin."
        )

    # Assign teams to QFs
    # QF order by match_code should be: QF1, QF2, QF3, QF4
    # Assignments:
    #   QF1: 1 vs 8
    #   QF2: 4 vs 5
    #   QF3: 3 vs 6
    #   QF4: 2 vs 7

    assignments = [
        (teams[0], teams[7]),  # QF1: 1 vs 8
        (teams[3], teams[4]),  # QF2: 4 vs 5
        (teams[2], teams[5]),  # QF3: 3 vs 6
        (teams[1], teams[6]),  # QF4: 2 vs 7
    ]

    matches_updated = 0
    for match, (team_a, team_b) in zip(qf_matches, assignments):
        match.team_a_id = team_a.id
        match.team_b_id = team_b.id
        session.add(match)
        matches_updated += 1

    return matches_updated


def inject_round_robin_teams(session: Session, event_id: int, schedule_version_id: int, teams: List[Team]) -> int:
    """
    Inject teams into round robin matches.

    Assigns teams to RR matches deterministically based on match ordering.
    For pool play formats, injects teams into pools.
    For true RR, uses standard round-robin pairing.

    Args:
        session: Database session
        event_id: Event ID
        schedule_version_id: Schedule version ID
        teams: List of teams in deterministic order

    Returns:
        Number of matches updated

    Raises:
        TeamInjectionError: If match structure is incompatible
    """
    n = len(teams)

    # Find all MAIN matches
    query = (
        select(Match)
        .where(Match.event_id == event_id, Match.schedule_version_id == schedule_version_id, Match.match_type == "MAIN")
        .order_by(Match.round_number, Match.sequence_in_round)
    )

    rr_matches = session.exec(query).all()

    if not rr_matches:
        raise TeamInjectionError(f"Cannot inject teams: No MAIN matches found for event {event_id}")

    # Check if this is pool play format (placeholder contains "Pool")
    is_pool_play = any("Pool" in m.placeholder_side_a for m in rr_matches)

    if is_pool_play:
        # Pool play format
        # Group matches by pool (round_number indicates pool number)
        pools = {}
        for match in rr_matches:
            pool_num = match.round_number
            if pool_num not in pools:
                pools[pool_num] = []
            pools[pool_num].append(match)

        # Distribute teams evenly across pools
        num_pools = len(pools)
        teams_per_pool = n // num_pools

        if n % num_pools != 0:
            raise TeamInjectionError(f"Cannot evenly distribute {n} teams across {num_pools} pools")

        matches_updated = 0
        for pool_num in sorted(pools.keys()):
            pool_matches = pools[pool_num]
            # Get teams for this pool
            start_idx = (pool_num - 1) * teams_per_pool
            end_idx = start_idx + teams_per_pool
            pool_teams = teams[start_idx:end_idx]

            # Generate RR pairings for this pool
            pairings = []
            for i in range(len(pool_teams)):
                for j in range(i + 1, len(pool_teams)):
                    pairings.append((pool_teams[i], pool_teams[j]))

            # Assign to matches
            for match, (team_a, team_b) in zip(pool_matches, pairings):
                match.team_a_id = team_a.id
                match.team_b_id = team_b.id
                session.add(match)
                matches_updated += 1

        return matches_updated
    else:
        # True round robin format
        expected_matches = n * (n - 1) // 2

        if len(rr_matches) != expected_matches:
            raise TeamInjectionError(
                f"Cannot inject teams: Expected {expected_matches} RR matches for {n} teams, "
                f"found {len(rr_matches)}. "
                f"Ensure match generation has created the correct RR structure."
            )

        # Generate RR pairings deterministically
        pairings = []
        for i in range(n):
            for j in range(i + 1, n):
                pairings.append((teams[i], teams[j]))

        # Assign teams to matches
        matches_updated = 0
        for match, (team_a, team_b) in zip(rr_matches, pairings):
            match.team_a_id = team_a.id
            match.team_b_id = team_b.id
            session.add(match)
            matches_updated += 1

        return matches_updated


def inject_teams_v1(session: Session, event_id: int, schedule_version_id: int, clear_existing: bool = True) -> dict:
    """
    Team Injection V1 - Deterministically assign team IDs to matches.

    Rules:
    - If team_count > 8: Reject (400)
    - If team_count == 8: Bracket injection (QFs only)
    - If team_count < 8: Round robin injection (all matches)

    Args:
        session: Database session
        event_id: Event ID
        schedule_version_id: Schedule version ID
        clear_existing: If True, clear all team assignments before injection

    Returns:
        dict with:
            - teams_count: int
            - matches_updated_count: int
            - injection_type: "bracket" | "round_robin"
            - warnings: List[str]

    Raises:
        TeamInjectionError: If injection cannot proceed
    """
    # Verify event exists and get team count
    event = session.get(Event, event_id)
    if not event:
        raise TeamInjectionError(f"Event {event_id} not found")

    team_count = event.team_count

    # Validate team count
    if team_count > 8:
        raise TeamInjectionError(
            f"Team injection V1 only supports up to 8 teams. Event has {team_count} teams configured."
        )

    if team_count < 2:
        raise TeamInjectionError(f"Cannot inject teams: Event must have at least 2 teams, has {team_count}")

    # Get teams in deterministic order
    teams = get_deterministic_teams(session, event_id)

    if len(teams) != team_count:
        raise TeamInjectionError(
            f"Event configured for {team_count} teams but only {len(teams)} teams found in database. "
            f"Create all teams before injection."
        )

    # Clear existing team assignments if requested
    if clear_existing:
        clear_query = select(Match).where(Match.event_id == event_id, Match.schedule_version_id == schedule_version_id)
        matches_to_clear = session.exec(clear_query).all()
        for match in matches_to_clear:
            match.team_a_id = None
            match.team_b_id = None
            session.add(match)

    # Determine injection strategy based on draw plan template
    warnings = []
    template_type = None

    if event.draw_plan_json:
        try:
            draw_plan = json.loads(event.draw_plan_json)
            template_type = draw_plan.get("template_type")
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

    # Decision logic:
    # - CANONICAL_32 template with 8 teams: bracket injection (QFs only)
    # - Other templates or team_count < 8: round robin injection

    if template_type == "CANONICAL_32" and team_count == 8:
        # Bracket injection (8-team single elimination)
        matches_updated = inject_bracket_8_teams(session, event_id, schedule_version_id, teams)
        injection_type = "bracket"
        warnings.append(
            "Only quarterfinals have team assignments. "
            "Semifinals, finals, and consolation matches remain as placeholders."
        )
    else:
        # Round robin injection (or pool play)
        matches_updated = inject_round_robin_teams(session, event_id, schedule_version_id, teams)
        injection_type = "round_robin"
        if template_type:
            warnings.append(f"Template type '{template_type}' treated as round robin injection.")

    # Commit changes
    session.commit()

    return {
        "teams_count": len(teams),
        "matches_updated_count": matches_updated,
        "injection_type": injection_type,
        "warnings": warnings,
    }
