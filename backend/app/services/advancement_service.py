"""
Phase 4 Advancement: When a match is finalized, auto-populate downstream match team slots.
WF/MAIN bracket only. Only updates team_a_id/team_b_id on future matches; no slot/assignment mutation.
"""
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models.match import Match

ROLE_WINNER = "WINNER"
ROLE_LOSER = "LOSER"


def _infer_role_from_bracket(match_code: Optional[str]) -> str:
    """Infer WINNER or LOSER role based on bracket label in match code.
    WW/LW brackets take winners of WF matches; WL/LL take losers."""
    if not match_code:
        return ROLE_WINNER
    for label in ("BWW", "BLW"):
        if label in match_code:
            return ROLE_WINNER
    for label in ("BWL", "BLL"):
        if label in match_code:
            return ROLE_LOSER
    return ROLE_WINNER


def _get_loser_id(match: Match) -> Optional[int]:
    """Derive loser team_id from match teams and winner."""
    if match.winner_team_id is None or match.team_a_id is None or match.team_b_id is None:
        return None
    if match.winner_team_id == match.team_a_id:
        return match.team_b_id
    if match.winner_team_id == match.team_b_id:
        return match.team_a_id
    return None


def resolve_all_dependencies(session: Session, schedule_version_id: int) -> Dict:
    """
    Bulk resolve dependencies for all finalized matches in a schedule version.

    Iterates through all FINAL matches with winner_team_id and applies advancement
    to populate downstream match team slots.

    Guarantees:
        - Idempotent (safe to call multiple times)
        - Deterministic ordering (processes by match_id)
        - No slot/assignment mutations
    """
    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()
    unknown_before = sum(
        1 for m in all_matches if m.team_a_id is None or m.team_b_id is None
    )

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
    """
    all_matches = session.exec(
        select(Match).where(Match.schedule_version_id == schedule_version_id)
    ).all()
    unknown_before = sum(
        1 for m in all_matches if m.team_a_id is None or m.team_b_id is None
    )

    simulatable = []
    for match in all_matches:
        if match.team_a_id is None or match.team_b_id is None:
            continue
        if match.runtime_status == "FINAL":
            continue
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

    simulatable.sort(key=lambda m: m.id)

    matches_simulated = 0
    teams_advanced = 0

    for match in simulatable:
        winner_id = min(match.team_a_id, match.team_b_id)
        match.winner_team_id = winner_id
        match.runtime_status = "FINAL"
        session.add(match)
        session.commit()

        count = apply_advancement_for_final_match(session, match.id)
        teams_advanced += count
        matches_simulated += 1

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
    Given a finalized match, advance its winner AND loser into downstream matches.
    Only updates team_a_id/team_b_id on matches in the same schedule_version_id.
    Returns count of downstream matches that had a team slot updated.
    Idempotent: calling twice produces same DB state.
    """
    match = session.get(Match, match_id)
    if not match:
        return 0
    winner_id = match.winner_team_id
    if winner_id is None:
        return 0
    if (match.runtime_status or "SCHEDULED") != "FINAL":
        return 0

    loser_id = _get_loser_id(match)
    version_id = match.schedule_version_id
    updated_count = 0

    def _resolve_team(role: str) -> Optional[int]:
        if role == ROLE_WINNER:
            return winner_id
        if role == ROLE_LOSER:
            return loser_id
        return None

    # Downstream where this match feeds slot A
    downstream_a = session.exec(
        select(Match).where(
            Match.schedule_version_id == version_id,
            Match.source_match_a_id == match_id,
        )
    ).all()
    for down in downstream_a:
        team_id = _resolve_team(down.source_a_role)
        if team_id is not None and (down.team_a_id is None or down.team_a_id == team_id):
            if down.team_a_id != team_id:
                down.team_a_id = team_id
                session.add(down)
                updated_count += 1

    # Downstream where this match feeds slot B
    downstream_b = session.exec(
        select(Match).where(
            Match.schedule_version_id == version_id,
            Match.source_match_b_id == match_id,
        )
    ).all()
    for down in downstream_b:
        team_id = _resolve_team(down.source_b_role)
        if team_id is not None and (down.team_b_id is None or down.team_b_id == team_id):
            if down.team_b_id != team_id:
                down.team_b_id = team_id
                session.add(down)
                updated_count += 1

    # Fallback for WF→bracket QF matches missing source wiring
    if not downstream_a and not downstream_b and match.match_code and match.match_type == "WF":
        mc = match.match_code
        ph_downs_a = session.exec(
            select(Match).where(
                Match.schedule_version_id == version_id,
                Match.placeholder_side_a == mc,
            )
        ).all()
        for down in ph_downs_a:
            role = _infer_role_from_bracket(down.match_code)
            if not down.source_match_a_id:
                down.source_match_a_id = match_id
                down.source_a_role = role
                session.add(down)
            team_id = _resolve_team(role)
            if team_id is not None and (down.team_a_id is None or down.team_a_id == team_id):
                if down.team_a_id != team_id:
                    down.team_a_id = team_id
                    session.add(down)
                    updated_count += 1

        ph_downs_b = session.exec(
            select(Match).where(
                Match.schedule_version_id == version_id,
                Match.placeholder_side_b == mc,
            )
        ).all()
        for down in ph_downs_b:
            role = _infer_role_from_bracket(down.match_code)
            if not down.source_match_b_id:
                down.source_match_b_id = match_id
                down.source_b_role = role
                session.add(down)
            team_id = _resolve_team(role)
            if team_id is not None and (down.team_b_id is None or down.team_b_id == team_id):
                if down.team_b_id != team_id:
                    down.team_b_id = team_id
                    session.add(down)
                    updated_count += 1

    if updated_count:
        session.commit()
    return updated_count


def apply_advancement_with_details(
    session: Session, match_id: int
) -> Dict[str, Any]:
    """
    Like apply_advancement_for_final_match but returns structured results
    with downstream updates and warnings for the desk UI.
    """
    match = session.get(Match, match_id)
    if not match:
        return {"downstream_updates": [], "warnings": []}

    winner_id = match.winner_team_id
    if winner_id is None:
        return {"downstream_updates": [], "warnings": []}
    if (match.runtime_status or "SCHEDULED") != "FINAL":
        return {"downstream_updates": [], "warnings": []}

    loser_id = _get_loser_id(match)
    version_id = match.schedule_version_id
    updates: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    def _resolve_team(role: str) -> Optional[int]:
        if role == ROLE_WINNER:
            return winner_id
        if role == ROLE_LOSER:
            return loser_id
        return None

    def _process_downstream(down: Match, slot: str, role: Optional[str]):
        team_id = _resolve_team(role) if role else None
        if team_id is None:
            return

        current = down.team_a_id if slot == "A" else down.team_b_id

        if current is not None and current != team_id:
            warnings.append({
                "match_id": down.id,
                "reason": "CONFLICT_EXISTING_TEAM",
                "detail": f"Slot {slot} already has team {current}, not overwriting with {team_id}",
            })
            return

        if current != team_id:
            if slot == "A":
                down.team_a_id = team_id
            else:
                down.team_b_id = team_id
            session.add(down)
            updates.append({
                "match_id": down.id,
                "slot_filled": slot,
                "team_id": team_id,
                "match_code": down.match_code,
                "match_type": down.match_type,
                "event_id": down.event_id,
                "role": role,
            })

    # Downstream where this match feeds slot A
    downstream_a = session.exec(
        select(Match).where(
            Match.schedule_version_id == version_id,
            Match.source_match_a_id == match_id,
        )
    ).all()
    for down in downstream_a:
        _process_downstream(down, "A", down.source_a_role)

    # Downstream where this match feeds slot B
    downstream_b = session.exec(
        select(Match).where(
            Match.schedule_version_id == version_id,
            Match.source_match_b_id == match_id,
        )
    ).all()
    for down in downstream_b:
        _process_downstream(down, "B", down.source_b_role)

    # Fallback for WF→bracket QF matches missing source wiring:
    # find bracket matches whose placeholder references this match's code
    if not downstream_a and not downstream_b and match.match_code and match.match_type == "WF":
        mc = match.match_code
        placeholder_downs_a = session.exec(
            select(Match).where(
                Match.schedule_version_id == version_id,
                Match.placeholder_side_a == mc,
            )
        ).all()
        for down in placeholder_downs_a:
            role = _infer_role_from_bracket(down.match_code)
            if not down.source_match_a_id:
                down.source_match_a_id = match_id
                down.source_a_role = role
                session.add(down)
            _process_downstream(down, "A", role)

        placeholder_downs_b = session.exec(
            select(Match).where(
                Match.schedule_version_id == version_id,
                Match.placeholder_side_b == mc,
            )
        ).all()
        for down in placeholder_downs_b:
            role = _infer_role_from_bracket(down.match_code)
            if not down.source_match_b_id:
                down.source_match_b_id = match_id
                down.source_b_role = role
                session.add(down)
            _process_downstream(down, "B", role)

    if updates:
        session.commit()

    # Auto-default: if a downstream match now has both teams and one is defaulted
    auto_updates, auto_warnings = _auto_default_if_needed(session, updates)
    updates.extend(auto_updates)
    warnings.extend(auto_warnings)

    return {"downstream_updates": updates, "warnings": warnings}


def _auto_default_if_needed(
    session: Session, updates: List[Dict[str, Any]]
) -> tuple:
    """After advancement, check if any updated match has a defaulted team and auto-finalize.
    Returns (extra_updates, extra_warnings) from cascading auto-defaults."""
    from datetime import datetime
    from app.models.team import Team

    extra_updates: List[Dict[str, Any]] = []
    extra_warnings: List[Dict[str, Any]] = []

    for u in updates:
        down = session.get(Match, u["match_id"])
        if not down or down.runtime_status == "FINAL":
            continue
        if not down.team_a_id or not down.team_b_id:
            continue
        if down.match_type == "WF":
            continue

        team_a = session.get(Team, down.team_a_id)
        team_b = session.get(Team, down.team_b_id)
        a_defaulted = team_a.is_defaulted if team_a else False
        b_defaulted = team_b.is_defaulted if team_b else False

        if not a_defaulted and not b_defaulted:
            continue
        if a_defaulted and b_defaulted:
            continue

        winner_id = down.team_b_id if a_defaulted else down.team_a_id
        dur = down.duration_minutes
        if dur <= 35:
            actual_score = "4-0"
        elif dur <= 60:
            actual_score = "8-0"
        else:
            actual_score = "6-0, 6-0"

        down.runtime_status = "FINAL"
        down.winner_team_id = winner_id
        down.completed_at = datetime.utcnow()
        down.score_json = {"display": "DEFAULT", "actual": actual_score}
        session.add(down)
        session.commit()

        extra_warnings.append({
            "match_id": down.id,
            "reason": "AUTO_DEFAULTED",
            "detail": f"Match #{down.id} ({down.match_code}) was auto-defaulted (team is defaulted for weekend)",
        })

        cascade = apply_advancement_with_details(session, down.id)
        extra_updates.extend(cascade.get("downstream_updates", []))
        extra_warnings.extend(cascade.get("warnings", []))

    return extra_updates, extra_warnings
