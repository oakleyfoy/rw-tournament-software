"""Enhanced team import with full field support.

Handles the complete WAR Tournaments export format:
  seed  avoid_group  display_name  full_name  event_name  rating  p1_cell  p1_email  p2_cell  p2_email

Tab-separated, pasted from Excel/Google Sheets.
Supports multi-group avoid edges (e.g. "A,B" means separate from both groups).
"""

import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select

from app.database import get_session
from app.models.event import Event
from app.models.team import Team

logger = logging.getLogger(__name__)

router = APIRouter(tags=["teams"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class EnhancedTeamImportRequest(BaseModel):
    """Request body for enhanced team import."""

    raw_text: str  # Tab-separated text pasted from Excel
    clear_existing: bool = True  # Clear existing teams before import


class ImportedTeamResult(BaseModel):
    """Result for a single imported team."""

    seed: Optional[int] = None
    avoid_group: Optional[str] = None
    display_name: str
    full_name: Optional[str] = None
    rating: Optional[float] = None
    p1_cell: Optional[str] = None
    p1_email: Optional[str] = None
    p2_cell: Optional[str] = None
    p2_email: Optional[str] = None
    team_id: Optional[int] = None  # Populated after DB insert
    status: str = "created"  # created | skipped | error
    error: Optional[str] = None


class EnhancedTeamImportResponse(BaseModel):
    """Response from enhanced team import."""

    event_id: int
    total_parsed: int
    created: int
    skipped: int
    errors: int
    avoid_edges_created: int
    teams: List[ImportedTeamResult]


class ParsedTeamRow(BaseModel):
    """Internal: a single parsed row from the pasted text."""

    line_number: int
    seed: Optional[int] = None
    avoid_group: Optional[str] = None  # Raw group string, e.g. "A,B"
    display_name: str = ""
    full_name: Optional[str] = None
    event_name: Optional[str] = None
    rating: Optional[float] = None
    p1_cell: Optional[str] = None
    p1_email: Optional[str] = None
    p2_cell: Optional[str] = None
    p2_email: Optional[str] = None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _is_email(value: str) -> bool:
    """Quick check if a value looks like an email."""
    return "@" in value and "." in value


def _is_phone(value: str) -> bool:
    """Quick check if a value looks like a phone number."""
    digits = re.sub(r"[^\d]", "", value)
    return len(digits) >= 7


def _is_rating(value: str) -> bool:
    """Check if a value looks like a numeric rating."""
    try:
        v = float(value)
        return 0 < v <= 20  # Ratings are typically 1-10 range
    except (ValueError, TypeError):
        return False


def _is_seed(value: str) -> bool:
    """Check if a value looks like a seed number."""
    try:
        v = int(value)
        return 0 < v <= 999
    except (ValueError, TypeError):
        return False


def _is_avoid_group(value: str) -> bool:
    """Check if a value looks like an avoid group (single letter or comma-separated letters, or dash)."""
    if value in ("—", "-", "–"):
        return True
    # Single letter or comma-separated letters like "A", "B", "A,B"
    return bool(re.match(r"^[A-Za-z](,[A-Za-z])*$", value.strip()))


def _clean_value(value: str) -> Optional[str]:
    """Clean a field value — return None for empty/placeholder values."""
    if not value:
        return None
    value = value.strip()
    if value in ("", "—", "-", "–", "N/A", "n/a", "none", "None"):
        return None
    return value


def parse_team_rows(raw_text: str) -> List[ParsedTeamRow]:
    """
    Parse tab-separated team data into structured rows.

    Expected format (all tab-separated):
      seed  avoid_group  display_name  full_name  event_name  rating  p1_cell  p1_email  p2_cell  p2_email

    But also handles shorter formats:
      seed  avoid_group  rating  display_name  (original 4-field format)
      seed  avoid_group  display_name  full_name  rating  p1_cell  p1_email  p2_cell  p2_email  (no event)

    The parser uses field content detection to handle variations.
    """
    rows = []
    lines = raw_text.strip().split("\n")

    for line_num, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue

        # Split by tab
        fields = line.split("\t")

        # Strip whitespace from all fields
        fields = [f.strip() for f in fields]

        row = ParsedTeamRow(line_number=line_num)

        if len(fields) >= 10:
            # Full format: seed, group, display_name, full_name, event, rating, p1_cell, p1_email, p2_cell, p2_email
            row.seed = int(fields[0]) if _is_seed(fields[0]) else None
            row.avoid_group = _clean_value(fields[1]) if _is_avoid_group(fields[1]) else None
            row.display_name = fields[2]
            row.full_name = _clean_value(fields[3])
            row.event_name = _clean_value(fields[4])
            row.rating = float(fields[5]) if _is_rating(fields[5]) else None
            row.p1_cell = _clean_value(fields[6])
            row.p1_email = _clean_value(fields[7]) if _is_email(fields[7]) else _clean_value(fields[7])
            row.p2_cell = _clean_value(fields[8])
            row.p2_email = _clean_value(fields[9]) if _is_email(fields[9]) else _clean_value(fields[9])

        elif len(fields) >= 9:
            # 9 fields: seed, group, display_name, full_name, rating, p1_cell, p1_email, p2_cell, p2_email
            row.seed = int(fields[0]) if _is_seed(fields[0]) else None
            row.avoid_group = _clean_value(fields[1]) if _is_avoid_group(fields[1]) else None
            row.display_name = fields[2]
            row.full_name = _clean_value(fields[3])
            row.rating = float(fields[4]) if _is_rating(fields[4]) else None
            row.p1_cell = _clean_value(fields[5])
            row.p1_email = _clean_value(fields[6])
            row.p2_cell = _clean_value(fields[7])
            row.p2_email = _clean_value(fields[8])

        elif len(fields) >= 4:
            # Original format: seed, avoid_group, rating, display_name
            # OR: seed, avoid_group, display_name, full_name
            row.seed = int(fields[0]) if _is_seed(fields[0]) else None
            row.avoid_group = _clean_value(fields[1]) if _is_avoid_group(fields[1]) else None

            # Detect if field 2 is a rating or display_name
            if _is_rating(fields[2]):
                row.rating = float(fields[2])
                row.display_name = " ".join(fields[3:])  # Rest is the name
            else:
                row.display_name = fields[2]
                if len(fields) > 3:
                    row.full_name = _clean_value(fields[3])

        elif len(fields) >= 2:
            # Minimal: seed, display_name
            row.seed = int(fields[0]) if _is_seed(fields[0]) else None
            row.display_name = fields[1] if len(fields) > 1 else fields[0]

        else:
            # Single field — treat as display_name
            row.display_name = fields[0]

        if row.display_name:
            rows.append(row)

    return rows


# ---------------------------------------------------------------------------
# Import endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/api/events/{event_id}/teams/import",
    response_model=EnhancedTeamImportResponse,
)
def import_teams_enhanced(
    event_id: int,
    body: EnhancedTeamImportRequest,
    session: Session = Depends(get_session),
):
    """
    Import teams from tab-separated text (pasted from Excel/Google Sheets).

    Handles full format with phone numbers, emails, and avoid groups.
    Creates avoid edges for teams sharing the same group code.
    Supports multi-group (e.g. "A,B") — team gets edges to ALL teams in both groups.
    """
    # Validate event exists
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(404, f"Event {event_id} not found")

    # Parse the raw text
    parsed_rows = parse_team_rows(body.raw_text)
    if not parsed_rows:
        raise HTTPException(400, "No valid team rows found in input")

    # Clear existing teams if requested
    if body.clear_existing:
        existing_teams = session.exec(
            select(Team).where(Team.event_id == event_id)
        ).all()
        for t in existing_teams:
            session.delete(t)
        session.flush()

    # Create teams
    results: List[ImportedTeamResult] = []
    created_teams: List[Team] = []
    # Map: group_code -> list of team IDs (for avoid edge creation)
    group_map: dict[str, list[int]] = {}

    for row in parsed_rows:
        result = ImportedTeamResult(
            seed=row.seed,
            avoid_group=row.avoid_group,
            display_name=row.display_name,
            full_name=row.full_name,
            rating=row.rating,
            p1_cell=row.p1_cell,
            p1_email=row.p1_email,
            p2_cell=row.p2_cell,
            p2_email=row.p2_email,
        )

        try:
            team = Team(
                event_id=event_id,
                name=row.display_name,
                seed=row.seed,
                rating=row.rating,
                p1_cell=row.p1_cell,
                p1_email=row.p1_email,
                p2_cell=row.p2_cell,
                p2_email=row.p2_email,
            )
            session.add(team)
            session.flush()  # Get the team ID

            result.team_id = team.id
            result.status = "created"
            created_teams.append(team)

            # Track group memberships for avoid edges
            if row.avoid_group:
                # Split multi-group: "A,B" -> ["A", "B"]
                groups = [g.strip().upper() for g in row.avoid_group.split(",")]
                for g in groups:
                    if g not in group_map:
                        group_map[g] = []
                    group_map[g].append(team.id)

        except Exception as e:
            result.status = "error"
            result.error = str(e)
            session.rollback()
            logger.warning(f"Failed to import team '{row.display_name}': {e}")

        results.append(result)

    # Create avoid edges for teams in the same group
    avoid_edges_created = 0
    try:
        from app.models.team_avoid_edge import TeamAvoidEdge

        for group_code, team_ids in group_map.items():
            if len(team_ids) < 2:
                continue
            # Create edges for all pairs in this group
            for i in range(len(team_ids)):
                for j in range(i + 1, len(team_ids)):
                    a_id = min(team_ids[i], team_ids[j])
                    b_id = max(team_ids[i], team_ids[j])

                    # Check if edge already exists (idempotent)
                    existing = session.exec(
                        select(TeamAvoidEdge).where(
                            TeamAvoidEdge.event_id == event_id,
                            TeamAvoidEdge.team_id_a == a_id,
                            TeamAvoidEdge.team_id_b == b_id,
                        )
                    ).first()

                    if not existing:
                        edge = TeamAvoidEdge(
                            event_id=event_id,
                            team_id_a=a_id,
                            team_id_b=b_id,
                            reason=f"group:{group_code}",
                        )
                        session.add(edge)
                        avoid_edges_created += 1

    except ImportError:
        logger.warning("TeamAvoidEdge model not found — skipping avoid edge creation")
    except Exception as e:
        logger.warning(f"Error creating avoid edges: {e}")

    session.commit()

    created_count = sum(1 for r in results if r.status == "created")
    error_count = sum(1 for r in results if r.status == "error")

    return EnhancedTeamImportResponse(
        event_id=event_id,
        total_parsed=len(parsed_rows),
        created=created_count,
        skipped=0,
        errors=error_count,
        avoid_edges_created=avoid_edges_created,
        teams=results,
    )


# ---------------------------------------------------------------------------
# Preview endpoint (parse without saving)
# ---------------------------------------------------------------------------


@router.post(
    "/api/events/{event_id}/teams/import/preview",
    response_model=EnhancedTeamImportResponse,
)
def preview_team_import(
    event_id: int,
    body: EnhancedTeamImportRequest,
    session: Session = Depends(get_session),
):
    """
    Preview team import — parses the data and shows what would be created,
    but does NOT write to the database.
    """
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(404, f"Event {event_id} not found")

    parsed_rows = parse_team_rows(body.raw_text)
    if not parsed_rows:
        raise HTTPException(400, "No valid team rows found in input")

    # Count avoid edges that would be created
    group_map: dict[str, list[int]] = {}
    results: List[ImportedTeamResult] = []

    for i, row in enumerate(parsed_rows):
        fake_id = i + 1  # Temporary ID for grouping calc

        result = ImportedTeamResult(
            seed=row.seed,
            avoid_group=row.avoid_group,
            display_name=row.display_name,
            full_name=row.full_name,
            rating=row.rating,
            p1_cell=row.p1_cell,
            p1_email=row.p1_email,
            p2_cell=row.p2_cell,
            p2_email=row.p2_email,
            team_id=None,
            status="preview",
        )
        results.append(result)

        if row.avoid_group:
            groups = [g.strip().upper() for g in row.avoid_group.split(",")]
            for g in groups:
                if g not in group_map:
                    group_map[g] = []
                group_map[g].append(fake_id)

    # Count avoid edges
    avoid_edge_count = 0
    for group_code, ids in group_map.items():
        if len(ids) >= 2:
            avoid_edge_count += len(ids) * (len(ids) - 1) // 2

    return EnhancedTeamImportResponse(
        event_id=event_id,
        total_parsed=len(parsed_rows),
        created=len(parsed_rows),  # Would create this many
        skipped=0,
        errors=0,
        avoid_edges_created=avoid_edge_count,
        teams=results,
    )
