"""Import snapshot, refresh diff, planner, and approved-plan persistence."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.models.tournament import Tournament
from app.models.tournament_import import TournamentDrawPlan, TournamentImport
from app.routes.tournaments import generate_tournament_days
from app.services.bracket_split_planner import approved_brackets_from_option, plan_snapshot
from app.services.canonical_teams import SnapshotTeam, validate_import_snapshot
from app.services.rw_os_client import RwOsClient


def snapshot_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {
            "tournamentId": payload.get("tournamentId"),
            "updatedAt": payload.get("updatedAt"),
            "version": payload.get("version"),
            "teams": payload.get("teams") or [],
            "waitlistTeams": payload.get("waitlistTeams") or [],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_teams(rows: list[dict[str, Any]]) -> list[SnapshotTeam]:
    return [SnapshotTeam.from_dict(row) for row in rows]


def serialize_import(row: TournamentImport) -> dict[str, Any]:
    return {
        "id": row.id,
        "tournamentId": row.tournament_id,
        "organizationSlug": row.organization_slug,
        "sourceTournamentId": row.source_tournament_id,
        "eventName": row.event_name,
        "eventDate": row.event_date,
        "importedAt": row.imported_at.isoformat() if row.imported_at else None,
        "sourceUpdatedAt": row.source_updated_at,
        "sourceVersion": row.source_version,
        "sourceTeamCount": row.source_team_count,
        "sourceHash": row.source_hash,
        "validationStatus": row.validation_status,
        "validationIssues": json.loads(row.validation_issues_json or "[]"),
        "refreshDiff": json.loads(row.refresh_diff_json) if row.refresh_diff_json else None,
        "planStatus": row.plan_status,
        "approvedAt": row.approved_at.isoformat() if row.approved_at else None,
        "teams": json.loads(row.snapshot_json or "[]"),
        "waitlistTeams": json.loads(row.waitlist_json or "[]"),
    }


def serialize_draw_plan(row: TournamentDrawPlan) -> dict[str, Any]:
    return {
        "id": row.id,
        "importId": row.import_id,
        "tournamentId": row.tournament_id,
        "drawKind": row.draw_kind,
        "drawLabel": row.draw_label,
        "teamCount": row.team_count,
        "optionKey": row.option_key,
        "isRecommended": row.is_recommended,
        "approved": row.approved,
        "option": json.loads(row.option_json),
        "brackets": json.loads(row.brackets_json),
    }


def imported_source_ids(session: Session) -> set[int]:
    rows = session.exec(select(TournamentImport.source_tournament_id)).all()
    return {int(value) for value in rows}


def list_importable_events(session: Session, client: Optional[RwOsClient] = None) -> list[dict[str, Any]]:
    client = client or RwOsClient()
    imported = imported_source_ids(session)
    events = []
    for event in client.list_events(include_historical=False):
        tournament_id = int(event["tournamentId"])
        already = tournament_id in imported
        events.append({**event, "alreadyImported": already, "available": not already})
    return [event for event in events if event["available"]]


def _planner_payload(import_row: TournamentImport) -> dict[str, Any]:
    teams = parse_teams(json.loads(import_row.snapshot_json or "[]"))
    return plan_snapshot(teams)


def _draw_counts(teams: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for team in teams:
        label = team.get("drawLabel") or team.get("drawKind") or "Unknown"
        counts[str(label)] += 1
    return dict(counts)


def build_import_response(session: Session, import_row: TournamentImport) -> dict[str, Any]:
    plans = session.exec(
        select(TournamentDrawPlan).where(TournamentDrawPlan.import_id == import_row.id)
    ).all()
    snapshot = json.loads(import_row.snapshot_json or "[]")
    waitlist = json.loads(import_row.waitlist_json or "[]")
    return {
        "import": serialize_import(import_row),
        "planner": _planner_payload(import_row),
        "drawCounts": _draw_counts(snapshot),
        "waitlistCount": len(waitlist),
        "approvedPlans": [serialize_draw_plan(plan) for plan in plans if plan.approved],
        "selectedPlans": [serialize_draw_plan(plan) for plan in plans],
        "bracketsCreated": False,
        "rwOsWrites": 0,
    }


def create_import_from_event(
    session: Session,
    source_tournament_id: int,
    *,
    client: Optional[RwOsClient] = None,
    organization_slug: str = "rw",
) -> TournamentImport:
    client = client or RwOsClient()
    if source_tournament_id in imported_source_ids(session):
        raise ValueError(f"RW-OS event {source_tournament_id} has already been imported.")
    payload = client.get_event(source_tournament_id)
    return persist_snapshot(session, payload, organization_slug=organization_slug)


def persist_snapshot(
    session: Session,
    payload: dict[str, Any],
    *,
    organization_slug: str = "rw",
    existing: Optional[TournamentImport] = None,
) -> TournamentImport:
    teams = parse_teams(payload.get("teams") or [])
    waitlist = parse_teams(payload.get("waitlistTeams") or [])
    issues = [issue.to_dict() for issue in validate_import_snapshot(teams, waitlist)]
    event_date = str(payload.get("eventDate") or date.today().isoformat())
    parsed_date = date.fromisoformat(event_date[:10])
    team_payload = [team.to_dict() for team in teams]
    waitlist_payload = [team.to_dict() for team in waitlist]
    source_id = int(payload["tournamentId"])
    source_hash = snapshot_hash(payload)

    if existing is None:
        tournament = Tournament(
            name=str(payload.get("eventName") or f"RW-OS {source_id}"),
            location=str(payload.get("venue") or "TBD"),
            timezone="America/New_York",
            start_date=parsed_date,
            end_date=parsed_date,
            notes=f"Imported from RW-OS tournament {source_id}. Bracket split planning only — no draws created.",
            source_rw_os_tournament_id=source_id,
            source_rw_os_organization_slug=organization_slug,
        )
        session.add(tournament)
        session.commit()
        session.refresh(tournament)
        generate_tournament_days(session, tournament.id, tournament.start_date, tournament.end_date)
        import_row = TournamentImport(
            tournament_id=tournament.id,
            organization_slug=organization_slug,
            source_tournament_id=source_id,
            event_name=tournament.name,
            event_date=event_date,
            source_updated_at=payload.get("updatedAt"),
            source_version=payload.get("version"),
            source_team_count=len(team_payload),
            source_hash=source_hash,
            snapshot_json=json.dumps(team_payload),
            waitlist_json=json.dumps(waitlist_payload),
            validation_status="needs_attention" if issues else "ok",
            validation_issues_json=json.dumps(issues),
            plan_status="imported",
        )
        session.add(import_row)
        session.commit()
        session.refresh(import_row)
        return import_row

    existing.source_updated_at = payload.get("updatedAt")
    existing.source_version = payload.get("version")
    existing.source_team_count = len(team_payload)
    existing.source_hash = source_hash
    existing.snapshot_json = json.dumps(team_payload)
    existing.waitlist_json = json.dumps(waitlist_payload)
    existing.validation_status = "needs_attention" if issues else "ok"
    existing.validation_issues_json = json.dumps(issues)
    existing.updated_at = datetime.utcnow()
    if existing.plan_status == "approved":
        existing.plan_status = "stale"
    session.add(existing)
    session.commit()
    session.refresh(existing)
    return existing


def compute_refresh_diff(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    prev_teams = {team["teamKey"]: team for team in previous.get("teams") or []}
    next_teams = {team["teamKey"]: team for team in current.get("teams") or []}
    added = [next_teams[key] for key in next_teams.keys() - prev_teams.keys()]
    removed = [prev_teams[key] for key in prev_teams.keys() - next_teams.keys()]
    partner_changes = []
    draw_changes = []
    rating_changes = []
    for key in next_teams.keys() & prev_teams.keys():
        before = prev_teams[key]
        after = next_teams[key]
        before_partners = {before["player1"]["rw_id"], before["player2"]["rw_id"]}
        after_partners = {after["player1"]["rw_id"], after["player2"]["rw_id"]}
        if before_partners != after_partners:
            partner_changes.append({"teamKey": key, "before": before, "after": after})
        if before.get("drawKind") != after.get("drawKind"):
            draw_changes.append({"teamKey": key, "before": before.get("drawKind"), "after": after.get("drawKind")})
        if before.get("teamRating") != after.get("teamRating"):
            rating_changes.append(
                {
                    "teamKey": key,
                    "before": before.get("teamRating"),
                    "after": after.get("teamRating"),
                }
            )
    return {
        "addedTeams": added,
        "withdrawnTeams": removed,
        "partnerChanges": partner_changes,
        "drawChanges": draw_changes,
        "ratingChanges": rating_changes,
        "addedCount": len(added),
        "withdrawnCount": len(removed),
        "changed": bool(added or removed or partner_changes or draw_changes or rating_changes),
        "previousHash": snapshot_hash(previous),
        "currentHash": snapshot_hash(current),
    }


def refresh_import(
    session: Session,
    import_row: TournamentImport,
    *,
    client: Optional[RwOsClient] = None,
    apply: bool = False,
) -> dict[str, Any]:
    client = client or RwOsClient()
    previous = {
        "tournamentId": import_row.source_tournament_id,
        "updatedAt": import_row.source_updated_at,
        "version": import_row.source_version,
        "teams": json.loads(import_row.snapshot_json or "[]"),
        "waitlistTeams": json.loads(import_row.waitlist_json or "[]"),
    }
    current = client.refresh_event(import_row.source_tournament_id, previous)
    diff = compute_refresh_diff(previous, current)
    import_row.refresh_diff_json = json.dumps(diff)
    import_row.updated_at = datetime.utcnow()
    if apply:
        persist_snapshot(session, current, organization_slug=import_row.organization_slug, existing=import_row)
    else:
        session.add(import_row)
        session.commit()
        session.refresh(import_row)
    return {
        "diff": diff,
        "applied": apply,
        "current": current if not apply else None,
        "import": serialize_import(import_row),
    }


def select_draw_structure(
    session: Session,
    import_row: TournamentImport,
    draw_kind: str,
    option_key: str,
    *,
    approve: bool = False,
) -> TournamentDrawPlan:
    planner = _planner_payload(import_row)
    draw = next((item for item in planner["draws"] if item["drawKind"] == draw_kind), None)
    if not draw:
        raise ValueError(f"Draw {draw_kind} was not found on this import.")
    option = next((item for item in draw["options"] if item["optionKey"] == option_key), None)
    if not option:
        raise ValueError(f"Structure {option_key} is not a valid option for {draw_kind}.")

    existing = session.exec(
        select(TournamentDrawPlan).where(
            TournamentDrawPlan.import_id == import_row.id,
            TournamentDrawPlan.draw_kind == draw_kind,
        )
    ).first()
    brackets = approved_brackets_from_option(option)
    now = datetime.utcnow()
    if existing:
        existing.option_key = option_key
        existing.is_recommended = bool(option.get("recommended"))
        existing.approved = approve
        existing.option_json = json.dumps(option)
        existing.brackets_json = json.dumps(brackets)
        existing.team_count = draw["teamCount"]
        existing.updated_at = now
        plan = existing
    else:
        plan = TournamentDrawPlan(
            import_id=import_row.id,
            tournament_id=import_row.tournament_id,
            draw_kind=draw_kind,
            draw_label=draw["drawLabel"],
            team_count=draw["teamCount"],
            option_key=option_key,
            is_recommended=bool(option.get("recommended")),
            approved=approve,
            option_json=json.dumps(option),
            brackets_json=json.dumps(brackets),
        )
        session.add(plan)

    if approve:
        import_row.plan_status = "approved"
        import_row.approved_at = now
    else:
        import_row.plan_status = "planned"
    import_row.updated_at = now
    session.add(import_row)
    session.commit()
    session.refresh(plan)
    return plan


def approve_structures(
    session: Session,
    import_row: TournamentImport,
    selections: dict[str, str],
) -> list[TournamentDrawPlan]:
    plans = []
    for draw_kind, option_key in selections.items():
        plans.append(select_draw_structure(session, import_row, draw_kind, option_key, approve=True))
    import_row.plan_status = "approved"
    import_row.approved_at = datetime.utcnow()
    session.add(import_row)
    session.commit()
    session.refresh(import_row)
    return plans
