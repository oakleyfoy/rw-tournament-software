"""
Schedule metadata sanity-check endpoint

Verifies all matches have required metadata for proper sorting and scheduling.
"""

import json
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament

router = APIRouter()


def get_match_stage(match: Match) -> str:
    """
    Determine match stage from match_type.
    Validates that match_type is one of the expected stage values.
    """
    match_type = match.match_type
    if match_type == "WF":
        return "WF"
    elif match_type == "MAIN":
        return "MAIN"
    elif match_type in ["CONSOLATION", "CONS"]:
        return "CONSOLATION"
    elif match_type == "PLACEMENT":
        return "PLACEMENT"
    elif match_type in ["RR", "BRACKET", "BRACKET", "BR"]:
        # Legacy format types - these should have been normalized to MAIN
        return "MAIN_LEGACY"
    else:
        return "UNKNOWN"


def validate_duration(duration_minutes: int) -> bool:
    """Check if duration is valid (60, 90, 105, or 120)"""
    return duration_minutes in [60, 90, 105, 120]


def get_match_sort_key(match: Match) -> tuple:
    """
    Generate deterministic sort key for matches.
    Priority order:
    1. Stage (WF < MAIN < CONSOLATION < PLACEMENT)
    2. round_index (ascending)
    3. Consolation tier (1 before 2, for CONSOLATION only)
    4. Placement type (stable order for PLACEMENT only)
    5. Tie-breakers: event_id, match_type, round_number, sequence_in_round, match_code

    Critical: MAIN Final (round_index=3) must sort BEFORE any PLACEMENT matches
    """
    stage = get_match_stage(match)
    stage_priority = {
        "WF": 1,
        "MAIN": 2,
        "MAIN_LEGACY": 2,
        "CONSOLATION": 3,
        "PLACEMENT": 4,  # PLACEMENT must be last
        "UNKNOWN": 99,
    }.get(stage, 99)

    # Consolation tier tie-breaker: Tier 1 before Tier 2
    consolation_tier = match.consolation_tier or 0  # 0 for non-consolation

    # Placement type tie-breaker: stable ordering within PLACEMENT
    placement_priority = {"MAIN_SF_LOSERS": 1, "CONS_R1_WINNERS": 2, "CONS_R1_LOSERS": 3}.get(
        match.placement_type or "", 0
    )

    return (
        stage_priority,
        match.round_index or 999,  # NULL round_index goes last
        consolation_tier,  # Tier 1 before Tier 2 within same round_index
        placement_priority,  # Stable placement ordering
        match.event_id,
        match.match_type,
        match.round_number or 0,
        match.sequence_in_round or 0,
        match.match_code,
    )


@router.get("/tournaments/{tournament_id}/schedule/versions/{version_id}/sanity-check")
def sanity_check_matches(
    tournament_id: int, version_id: int, session: Session = Depends(get_session)
) -> Dict[str, Any]:
    """
    Sanity-check all matches in a schedule version.

    Returns a report with:
    - Metadata completeness statistics
    - Stage classification breakdown
    - Round alignment verification
    - Determinism verification
    - Issues found
    """
    # Validate tournament and version
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    version = session.get(ScheduleVersion, version_id)
    if not version or version.tournament_id != tournament_id:
        raise HTTPException(status_code=404, detail="Schedule version not found")

    # Get all matches for this version
    matches = session.exec(
        select(Match).where(Match.tournament_id == tournament_id, Match.schedule_version_id == version_id)
    ).all()

    total_matches = len(matches)

    if total_matches == 0:
        return {"status": "empty", "total_matches": 0, "message": "No matches found in this schedule version"}

    # Initialize counters and issues
    issues: List[str] = []
    consolation_issues: List[str] = []  # Initialize early for consolation validation
    consolation_counts_ok = True  # Initialize early
    rr_consolation_ok = True  # Initialize early
    stage_counts = {"WF": 0, "MAIN": 0, "CONSOLATION": 0, "MAIN_LEGACY": 0, "UNKNOWN": 0}
    round_indices_by_stage: Dict[str, List[int]] = {"WF": [], "MAIN": [], "CONSOLATION": []}

    # Required field checks
    missing_fields = {
        "stage": 0,
        "round_index": 0,
        "duration_minutes": 0,
        "schedule_version_id": 0,
        "event_id": 0,
        "sequence_in_round": 0,
    }

    invalid_durations = 0
    duration_counts = {60: 0, 90: 0, 105: 0, 120: 0}

    # Get events to determine template types
    event_ids = set(m.event_id for m in matches)
    events_by_id = {}
    if event_ids:
        events = session.exec(select(Event).where(Event.id.in_(event_ids))).all()
        events_by_id = {e.id: e for e in events}

    # Track consolation metadata
    consolation_metadata = {
        "by_event": {},  # event_id -> {tier1_count, tier2_count, issues}
        "rr_with_consolation": [],  # event_ids that shouldn't have consolation
    }

    # Check each match
    for match in matches:
        stage = get_match_stage(match)

        # Count by stage
        if stage in stage_counts:
            stage_counts[stage] += 1
        else:
            stage_counts["UNKNOWN"] += 1

        # Check required fields
        if not match.match_type or stage == "UNKNOWN":
            missing_fields["stage"] += 1
            issues.append(
                f"Match {match.id} ({match.match_code}): Invalid or missing stage classification (match_type='{match.match_type}')"
            )

        if match.round_index is None:
            missing_fields["round_index"] += 1
            issues.append(f"Match {match.id} ({match.match_code}): Missing round_index")
        else:
            if stage in round_indices_by_stage:
                if match.round_index not in round_indices_by_stage[stage]:
                    round_indices_by_stage[stage].append(match.round_index)

        if match.duration_minutes is None:
            missing_fields["duration_minutes"] += 1
            issues.append(f"Match {match.id} ({match.match_code}): Missing duration_minutes")
        elif not validate_duration(match.duration_minutes):
            invalid_durations += 1
            issues.append(
                f"Match {match.id} ({match.match_code}): Invalid duration_minutes={match.duration_minutes} (must be 60, 90, 105, or 120)"
            )
        else:
            duration_counts[match.duration_minutes] += 1

        if not match.schedule_version_id:
            missing_fields["schedule_version_id"] += 1

        if not match.event_id:
            missing_fields["event_id"] += 1

        if match.sequence_in_round is None:
            missing_fields["sequence_in_round"] += 1
            issues.append(f"Match {match.id} ({match.match_code}): Missing sequence_in_round (needed for tie-breaking)")

        # Consolation-specific validation
        if stage == "CONSOLATION":
            event = events_by_id.get(match.event_id)
            if event:
                # Parse template type from draw_plan
                draw_plan = None
                if event.draw_plan_json:
                    try:
                        draw_plan = json.loads(event.draw_plan_json)
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        pass

                template_type = draw_plan.get("template_type", "RR_ONLY") if draw_plan else "RR_ONLY"

                # RR templates should never have consolation
                if template_type == "RR_ONLY":
                    consolation_metadata["rr_with_consolation"].append(match.event_id)
                    issues.append(
                        f"Match {match.id} ({match.match_code}): CONSOLATION match found in RR_ONLY event (event_id={match.event_id})"
                    )

                # Track consolation metadata
                if match.event_id not in consolation_metadata["by_event"]:
                    consolation_metadata["by_event"][match.event_id] = {
                        "tier1_count": 0,
                        "tier2_count": 0,
                        "tier1_round_index_ok": True,
                        "tier2_round_index_ok": True,
                        "tier1_tier_ok": True,
                        "tier2_tier_ok": True,
                        "template_type": template_type,
                        "team_count": event.team_count,
                    }

                # Validate tier metadata
                if match.consolation_tier == 1:
                    consolation_metadata["by_event"][match.event_id]["tier1_count"] += 1
                    if match.round_index != 1:
                        consolation_metadata["by_event"][match.event_id]["tier1_round_index_ok"] = False
                        issues.append(
                            f"Match {match.id} ({match.match_code}): Tier 1 consolation has round_index={match.round_index}, expected 1"
                        )
                elif match.consolation_tier == 2:
                    consolation_metadata["by_event"][match.event_id]["tier2_count"] += 1
                    if match.round_index != 2:
                        consolation_metadata["by_event"][match.event_id]["tier2_round_index_ok"] = False
                        issues.append(
                            f"Match {match.id} ({match.match_code}): Tier 2 consolation has round_index={match.round_index}, expected 2"
                        )
                else:
                    if match.consolation_tier is None:
                        issues.append(
                            f"Match {match.id} ({match.match_code}): CONSOLATION match missing consolation_tier"
                        )
                    else:
                        issues.append(
                            f"Match {match.id} ({match.match_code}): Invalid consolation_tier={match.consolation_tier} (must be 1 or 2)"
                        )

    # Sort matches to verify determinism
    sorted_matches = sorted(matches, key=get_match_sort_key)
    [m.id for m in sorted_matches]
    [m.id for m in matches]

    # Check round alignment for MAIN matches
    main_round_alignment_ok = True
    main_round_issues = []

    main_matches = [m for m in matches if get_match_stage(m) == "MAIN"]
    if main_matches:
        # Group MAIN matches by round_index
        main_by_round: Dict[int, List[Match]] = {}
        for match in main_matches:
            if match.round_index:
                if match.round_index not in main_by_round:
                    main_by_round[match.round_index] = []
                main_by_round[match.round_index].append(match)

        # Check if all matches in same round_index can be interleaved
        # (No special casing needed for RR vs BRACKET)
        for round_idx, round_matches in main_by_round.items():
            match_types_in_round = set(m.match_type for m in round_matches)
            if "RR" in match_types_in_round or "BRACKET" in match_types_in_round:
                main_round_alignment_ok = False
                main_round_issues.append(
                    f"Round {round_idx} has legacy format types: {match_types_in_round}. "
                    "These should be normalized to 'MAIN' with unified round_index."
                )

    # Check CONSOLATION ordering and counts
    consolation_ordering_ok = True
    consolation_counts_ok = True
    rr_consolation_ok = True

    consolation_matches = [m for m in matches if get_match_stage(m) == "CONSOLATION"]
    if consolation_matches:
        consolation_round_indices = sorted(set(m.round_index for m in consolation_matches if m.round_index))
        main_round_indices = sorted(set(m.round_index for m in main_matches if m.round_index))

        if consolation_round_indices and main_round_indices:
            # Check if any consolation round appears before corresponding main round
            for cons_round in consolation_round_indices:
                min_main_round = min(main_round_indices)
                if cons_round < min_main_round:
                    consolation_ordering_ok = False
                    consolation_issues.append(
                        f"CONSOLATION round {cons_round} appears before any MAIN rounds. "
                        "Consolation should start after Round 1 MAIN."
                    )

        # Validate consolation counts for bracket events
        for event_id, metadata in consolation_metadata["by_event"].items():
            event = events_by_id.get(event_id)
            if not event:
                continue

            template_type = metadata["template_type"]
            team_count = metadata["team_count"]

            if template_type == "CANONICAL_32":
                # CANONICAL_32 is now an 8-team bracket
                if team_count != 8:
                    consolation_counts_ok = False
                    consolation_issues.append(f"Event {event_id}: CANONICAL_32 requires team_count=8, got {team_count}")
                    continue

                # Determine expected counts based on guarantee
                guarantee = event.guarantee_selected or 5
                expected_tier1 = 2  # Always 2 for 8-team bracket
                expected_tier2 = 1 if guarantee == 5 else 0  # 1 if guarantee 5, else 0

                if metadata["tier1_count"] != expected_tier1:
                    consolation_counts_ok = False
                    consolation_issues.append(
                        f"Event {event_id}: Tier 1 consolation count={metadata['tier1_count']}, expected {expected_tier1} (8-team bracket)"
                    )

                if metadata["tier2_count"] != expected_tier2:
                    consolation_counts_ok = False
                    consolation_issues.append(
                        f"Event {event_id}: Tier 2 consolation count={metadata['tier2_count']}, expected {expected_tier2} (guarantee={guarantee})"
                    )

                if not metadata["tier1_round_index_ok"]:
                    consolation_issues.append(f"Event {event_id}: Tier 1 consolation has incorrect round_index")

                if not metadata["tier2_round_index_ok"]:
                    consolation_issues.append(f"Event {event_id}: Tier 2 consolation has incorrect round_index")

                if not metadata["tier1_tier_ok"]:
                    consolation_issues.append(f"Event {event_id}: Tier 1 consolation has incorrect tier value")

                if not metadata["tier2_tier_ok"]:
                    consolation_issues.append(f"Event {event_id}: Tier 2 consolation has incorrect tier value")

    # Check RR events don't have consolation
    rr_consolation_ok = len(consolation_metadata["rr_with_consolation"]) == 0
    if not rr_consolation_ok:
        for event_id in set(consolation_metadata["rr_with_consolation"]):
            consolation_issues.append(f"Event {event_id}: RR_ONLY event has CONSOLATION matches (should be 0)")

    # Check MAIN bracket structure for 8-team brackets
    main_bracket_ok = True
    main_bracket_issues = []

    for event_id in event_ids:
        event = events_by_id.get(event_id)
        if not event:
            continue

        # Parse template type
        draw_plan = None
        if event.draw_plan_json:
            try:
                draw_plan = json.loads(event.draw_plan_json)
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass

        template_type = draw_plan.get("template_type", "RR_ONLY") if draw_plan else "RR_ONLY"

        if template_type == "CANONICAL_32":
            # Validate 8-team bracket MAIN structure
            event_main_matches = [m for m in matches if m.event_id == event_id and get_match_stage(m) == "MAIN"]

            # Count by round_index
            round_counts = {}
            for match in event_main_matches:
                round_counts[match.round_index] = round_counts.get(match.round_index, 0) + 1

            # Expected: Round 1 (QF) = 4, Round 2 (SF) = 2, Round 3 (Final) = 1
            expected_rounds = {1: 4, 2: 2, 3: 1}

            for round_idx, expected_count in expected_rounds.items():
                actual_count = round_counts.get(round_idx, 0)
                if actual_count != expected_count:
                    main_bracket_ok = False
                    main_bracket_issues.append(
                        f"Event {event_id}: MAIN round {round_idx} has {actual_count} matches, expected {expected_count}"
                    )

    # Check PLACEMENT matches for Guarantee 5 bracket events
    placement_ok = True
    placement_issues = []
    placement_matches = [m for m in matches if get_match_stage(m) == "PLACEMENT"]

    for event_id in event_ids:
        event = events_by_id.get(event_id)
        if not event:
            continue

        # Parse template type
        draw_plan = None
        if event.draw_plan_json:
            try:
                draw_plan = json.loads(event.draw_plan_json)
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass

        template_type = draw_plan.get("template_type", "RR_ONLY") if draw_plan else "RR_ONLY"
        guarantee = event.guarantee_selected or 5

        event_placement_matches = [m for m in placement_matches if m.event_id == event_id]

        if template_type == "CANONICAL_32":
            # Bracket event: validate placement matches
            expected_placement_count = 3 if guarantee == 5 else 0
            actual_placement_count = len(event_placement_matches)

            if actual_placement_count != expected_placement_count:
                placement_ok = False
                placement_issues.append(
                    f"Event {event_id}: PLACEMENT count={actual_placement_count}, expected {expected_placement_count} (guarantee={guarantee})"
                )

            # Validate placement types if matches exist
            if event_placement_matches:
                placement_types_found = set(m.placement_type for m in event_placement_matches)
                expected_types = {"MAIN_SF_LOSERS", "CONS_R1_WINNERS", "CONS_R1_LOSERS"}

                if placement_types_found != expected_types:
                    placement_ok = False
                    placement_issues.append(
                        f"Event {event_id}: PLACEMENT types={placement_types_found}, expected {expected_types}"
                    )
        elif template_type == "RR_ONLY":
            # RR events should never have placement matches
            if event_placement_matches:
                placement_ok = False
                placement_issues.append(
                    f"Event {event_id}: RR_ONLY event has {len(event_placement_matches)} PLACEMENT matches (should be 0)"
                )

    # Calculate completeness
    complete_matches = 0
    for match in matches:
        if (
            match.match_type
            and match.round_index is not None
            and match.duration_minutes
            and validate_duration(match.duration_minutes)
            and match.schedule_version_id
            and match.event_id
            and match.sequence_in_round is not None
        ):
            complete_matches += 1

    # Prepare report
    report = {
        "status": "ok" if len(issues) == 0 else "issues_found",
        "total_matches": total_matches,
        "complete_matches": complete_matches,
        "completeness_percentage": round(100 * complete_matches / total_matches, 1) if total_matches > 0 else 0,
        "metadata_completeness": {
            "missing_stage": missing_fields["stage"],
            "missing_round_index": missing_fields["round_index"],
            "missing_duration_minutes": missing_fields["duration_minutes"],
            "missing_sequence_in_round": missing_fields["sequence_in_round"],
            "invalid_durations": invalid_durations,
        },
        "stage_breakdown": stage_counts,
        "round_indices_by_stage": {stage: sorted(indices) for stage, indices in round_indices_by_stage.items()},
        "duration_breakdown": duration_counts,
        "main_stage_alignment": {
            "status": "ok" if main_round_alignment_ok else "needs_fix",
            "issues": main_round_issues,
        },
        "consolation_ordering": {
            "status": "ok"
            if (consolation_ordering_ok and consolation_counts_ok and rr_consolation_ok)
            else "needs_fix",
            "counts_ok": consolation_counts_ok,
            "rr_consolation_ok": rr_consolation_ok,
            "issues": consolation_issues,
            "consolation_by_event": consolation_metadata["by_event"],
        },
        "main_bracket_structure": {"status": "ok" if main_bracket_ok else "needs_fix", "issues": main_bracket_issues},
        "placement_validation": {"status": "ok" if placement_ok else "needs_fix", "issues": placement_issues},
        "determinism": {
            "status": "ok" if missing_fields["sequence_in_round"] == 0 else "missing_tie_breakers",
            "has_sequence_in_round": missing_fields["sequence_in_round"] == 0,
            "has_match_code": all(m.match_code for m in matches),
        },
        "issues": issues[:50],  # Limit to first 50 issues
        "total_issues": len(issues),
    }

    return report
