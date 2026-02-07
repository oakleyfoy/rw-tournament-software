"""
Phase 4 Advancement: When a match is finalized, auto-populate downstream match team slots.
WF/MAIN bracket only. Only updates team_a_id/team_b_id on future matches; no slot/assignment mutation.
"""
from typing import Dict, List

from sqlmodel import Session, select

from app.models.match import Match

ROLE_WINNER = "WINNER"


def resolve_all_dependencies(session: Session, schedule_version_id: int) -> Dict:
    """
    Bulk resolve dependencies for all finalized matches in a schedule version.
    
    Iterates through all FINAL matches with winner_team_id and applies advancement
    to populate downstream match team slots.
    
    Returns:
        Dict with:
        - matches_processed: number of finalized matches processed
        - teams_advanced: total number of downstream team slots filled
        - unknown_before: count of matches with null teams before
        - unknown_after: count of matches with null teams after
    
    Guarantees:
        - Idempotent (safe to call multiple times)
        - Deterministic ordering (processes by match_id)
        - No slot/assignment mutations
    """
    # Count unknown teams before
    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()
    unknown_before = sum(
        1 for m in all_matches if m.team_a_id is None or m.team_b_id is None
    )
    
    # Find all finalized matches with winners, ordered deterministically
    finalized_matches = session.exec(
        select(Match)
        .where(
            Match.schedule_version_id == schedule_version_id,
            Match.runtime_status == "FINAL",
            Match.winner_team_id.is_not(None),
        )
        .order_by(Match.id)
    ).all()
    
    matches_processed = 0
    teams_advanced = 0
    
    for match in finalized_matches:
        count = apply_advancement_for_final_match(session, match.id)
        if count > 0:
            teams_advanced += count
        matches_processed += 1
    
    # Count unknown teams after
    # Need to refresh from DB
    session.expire_all()
    all_matches_after = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()
    unknown_after = sum(
        1 for m in all_matches_after if m.team_a_id is None or m.team_b_id is None
    )
    
    return {
        "matches_processed": matches_processed,
        "teams_advanced": teams_advanced,
        "unknown_before": unknown_before,
        "unknown_after": unknown_after,
    }


def simulate_advancement_higher_seed_wins(
    session: Session, schedule_version_id: int
) -> Dict:
    """
    DEV-ONLY: Simulate advancement by assuming higher seed (lower team_id) wins.
    
    For each WF/dependency-source match that has both teams assigned but no winner:
    - Set winner_team_id = min(team_a_id, team_b_id)
    - Set runtime_status = "FINAL"
    - Run advancement to fill downstream slots
    
    This is for testing only - allows verifying the advancement pipeline
    without manual match result entry.
    
    Returns:
        Dict with:
        - matches_simulated: number of matches auto-finalized
        - teams_advanced: total downstream slots filled
        - unknown_before: count of unknown-team matches before
        - unknown_after: count of unknown-team matches after
    
    Guarantees:
        - Deterministic (same input → same output)
        - Processes in match_id order
        - No slot/assignment mutations
    """
    # Count unknown teams before
    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()
    unknown_before = sum(
        1 for m in all_matches if m.team_a_id is None or m.team_b_id is None
    )
    
    # Find matches that:
    # - Have both teams assigned
    # - Are not yet FINAL
    # - Are dependency sources for other matches (WF/bracket)
    simulatable = []
    
    for match in all_matches:
        if match.team_a_id is None or match.team_b_id is None:
            continue
        if match.runtime_status == "FINAL":
            continue
        # Check if this match is a source for any downstream match
        is_source = session.exec(
            select(Match).where(
                Match.schedule_version_id == schedule_version_id,
                (
                    (Match.source_match_a_id == match.id) |
                    (Match.source_match_b_id == match.id)
                ),
            )
        ).first()
        if is_source:
            simulatable.append(match)
    
    # Sort deterministically
    simulatable.sort(key=lambda m: m.id)
    
    matches_simulated = 0
    teams_advanced = 0
    
    for match in simulatable:
        # Higher seed wins (lower team_id)
        winner_id = min(match.team_a_id, match.team_b_id)
        match.winner_team_id = winner_id
        match.runtime_status = "FINAL"
        session.add(match)
        session.commit()
        
        # Apply advancement
        count = apply_advancement_for_final_match(session, match.id)
        teams_advanced += count
        matches_simulated += 1
    
    # Count unknown teams after
    session.expire_all()
    all_matches_after = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()
    unknown_after = sum(
        1 for m in all_matches_after if m.team_a_id is None or m.team_b_id is None
    )
    
    return {
        "matches_simulated": matches_simulated,
        "teams_advanced": teams_advanced,
        "unknown_before": unknown_before,
        "unknown_after": unknown_after,
    }


def apply_advancement_for_final_match(session: Session, match_id: int) -> int:
    """
    Given a finalized match, advance its winner into downstream matches that list this match
    as source (source_match_a_id or source_match_b_id with role WINNER).
    Only updates team_a_id/team_b_id on matches in the same schedule_version_id.
    Returns count of downstream matches that had a team slot updated.
    Idempotent: calling twice produces same DB state (only set if null or already same).
    """
    match = session.get(Match, match_id)
    if not match:
        return 0
    winner_id = match.winner_team_id
    if winner_id is None:
        return 0
    if (match.runtime_status or "SCHEDULED") != "FINAL":
        return 0

    version_id = match.schedule_version_id
    updated_count = 0

    # Downstream where this match feeds slot A (winner -> team_a)
    downstream_a = session.exec(
        select(Match).where(
            Match.schedule_version_id == version_id,
            Match.source_match_a_id == match_id,
            Match.source_a_role == ROLE_WINNER,
        )
    ).all()
    for down in downstream_a:
        if down.team_a_id is None or down.team_a_id == winner_id:
            if down.team_a_id != winner_id:
                down.team_a_id = winner_id
                session.add(down)
                updated_count += 1

    # Downstream where this match feeds slot B (winner -> team_b)
    downstream_b = session.exec(
        select(Match).where(
            Match.schedule_version_id == version_id,
            Match.source_match_b_id == match_id,
            Match.source_b_role == ROLE_WINNER,
        )
    ).all()
    for down in downstream_b:
        if down.team_b_id is None or down.team_b_id == winner_id:
            if down.team_b_id != winner_id:
                down.team_b_id = winner_id
                session.add(down)
                updated_count += 1

    if updated_count:
        session.commit()
    return updated_count
