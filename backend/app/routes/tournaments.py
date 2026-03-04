from datetime import date, datetime, time, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator, model_validator
from sqlmodel import Session, func, select, text

from app.database import get_session
from app.models.court_state import TournamentCourtState
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.match_lock import MatchLock
from app.models.player import Player
from app.models.policy_run import PolicyRun
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.slot_lock import SlotLock
from app.models.sms_template import SmsTemplate
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.team_player import TeamPlayer
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.models.tournament_sms_settings import TournamentSmsSettings
from app.models.tournament_time_window import TournamentTimeWindow
from app.utils.courts import parse_court_names

router = APIRouter()


class TournamentCreate(BaseModel):
    name: str
    location: str
    timezone: str
    start_date: date
    end_date: date
    notes: Optional[str] = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v):
        if not v or not v.strip():
            raise ValueError("timezone is required")
        return v.strip()

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class TournamentUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    timezone: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None
    use_time_windows: Optional[bool] = None
    court_names: Optional[List[str]] = None

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class TournamentResponse(BaseModel):
    id: int
    name: str
    location: str
    timezone: str
    start_date: date
    end_date: date
    notes: Optional[str]
    use_time_windows: bool
    court_names: Optional[List[str]] = None
    public_schedule_version_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("court_names", mode="before")
    @classmethod
    def normalize_court_names(cls, v):
        """Handle legacy DB storage: court_names may be string '1,2,3' instead of list."""
        if v is None:
            return None
        return parse_court_names(v)  # handles str and list, returns List[str]

    class Config:
        from_attributes = True


def generate_tournament_days(session: Session, tournament_id: int, start_date: date, end_date: date):
    """Generate tournament days for the date range"""
    current_date = start_date
    while current_date <= end_date:
        # Check if day already exists
        existing = session.exec(
            select(TournamentDay).where(
                TournamentDay.tournament_id == tournament_id, TournamentDay.date == current_date
            )
        ).first()

        if not existing:
            day = TournamentDay(
                tournament_id=tournament_id,
                date=current_date,
                is_active=True,
                start_time=time(8, 0),
                end_time=time(18, 0),
                courts_available=0,
            )
            session.add(day)
        current_date += timedelta(days=1)
    session.commit()


@router.get("/tournaments", response_model=List[TournamentResponse])
def list_tournaments(session: Session = Depends(get_session)):
    """List all tournaments"""
    tournaments = session.exec(select(Tournament)).all()
    return tournaments


@router.post("/tournaments", response_model=TournamentResponse, status_code=201)
def create_tournament(tournament_data: TournamentCreate, session: Session = Depends(get_session)):
    """Create a new tournament and auto-generate days"""
    tournament = Tournament(**tournament_data.model_dump())
    session.add(tournament)
    session.commit()
    session.refresh(tournament)

    # Auto-generate days
    generate_tournament_days(session, tournament.id, tournament.start_date, tournament.end_date)

    return tournament


@router.get("/tournaments/{tournament_id}", response_model=TournamentResponse)
def get_tournament(tournament_id: int, session: Session = Depends(get_session)):
    """Get a tournament by ID"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return tournament


@router.put("/tournaments/{tournament_id}", response_model=TournamentResponse)
def update_tournament(tournament_id: int, tournament_data: TournamentUpdate, session: Session = Depends(get_session)):
    """Update a tournament and manage days based on date range changes"""
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    old_start = tournament.start_date
    old_end = tournament.end_date

    # Update tournament fields
    update_data = tournament_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tournament, field, value)

    tournament.updated_at = datetime.utcnow()
    session.add(tournament)
    session.commit()

    # Handle date range changes
    new_start = tournament.start_date
    new_end = tournament.end_date

    if old_start != new_start or old_end != new_end:
        # Remove days outside the new range
        session.exec(
            select(TournamentDay)
            .where(TournamentDay.tournament_id == tournament_id)
            .where((TournamentDay.date < new_start) | (TournamentDay.date > new_end))
        )
        days_to_remove = session.exec(
            select(TournamentDay).where(
                TournamentDay.tournament_id == tournament_id,
                (TournamentDay.date < new_start) | (TournamentDay.date > new_end),
            )
        ).all()
        for day in days_to_remove:
            session.delete(day)

        # Add missing days for new range
        generate_tournament_days(session, tournament_id, new_start, new_end)

    session.refresh(tournament)
    return tournament


@router.post("/tournaments/{tournament_id}/duplicate", response_model=TournamentResponse, status_code=201)
def duplicate_tournament(tournament_id: int, session: Session = Depends(get_session)):
    """
    Deep-duplicate a tournament snapshot.

    Copies tournament configuration and operational state, including:
    - tournament fields (courts, dates, timezone, notes)
    - days + time windows
    - events + teams + avoid edges
    - players + team_player links
    - schedule versions + slots + matches + assignments
    - match/slot locks + policy runs
    - court state + SMS settings/templates
    """
    try:
        source_tournament = session.get(Tournament, tournament_id)
        if not source_tournament:
            raise HTTPException(status_code=404, detail="Tournament not found")

        # 1) Create destination tournament shell.
        new_tournament = Tournament(
            name=f"{source_tournament.name} (Copy)",
            location=source_tournament.location,
            timezone=source_tournament.timezone,
            start_date=source_tournament.start_date,
            end_date=source_tournament.end_date,
            notes=source_tournament.notes,
            use_time_windows=source_tournament.use_time_windows,
            court_names=list(source_tournament.court_names or []),
        )
        session.add(new_tournament)
        session.flush()

        source_days = session.exec(
            select(TournamentDay).where(TournamentDay.tournament_id == tournament_id)
        ).all()
        source_windows = session.exec(
            select(TournamentTimeWindow).where(TournamentTimeWindow.tournament_id == tournament_id)
        ).all()
        source_events = session.exec(
            select(Event).where(Event.tournament_id == tournament_id)
        ).all()
        source_versions = session.exec(
            select(ScheduleVersion)
            .where(ScheduleVersion.tournament_id == tournament_id)
            .order_by(ScheduleVersion.version_number.asc(), ScheduleVersion.id.asc())
        ).all()
        source_slots = session.exec(
            select(ScheduleSlot).where(ScheduleSlot.tournament_id == tournament_id)
        ).all()
        source_matches = session.exec(
            select(Match).where(Match.tournament_id == tournament_id)
        ).all()
        source_court_state = session.exec(
            select(TournamentCourtState).where(
                TournamentCourtState.tournament_id == tournament_id
            )
        ).all()
        source_sms_settings = session.exec(
            select(TournamentSmsSettings).where(
                TournamentSmsSettings.tournament_id == tournament_id
            )
        ).first()
        source_sms_templates = session.exec(
            select(SmsTemplate).where(SmsTemplate.tournament_id == tournament_id)
        ).all()

        source_event_ids = [e.id for e in source_events if e.id is not None]
        source_teams = session.exec(
            select(Team).where(Team.event_id.in_(source_event_ids))  # type: ignore
        ).all() if source_event_ids else []
        source_team_ids = [t.id for t in source_teams if t.id is not None]

        source_avoid_edges = session.exec(
            select(TeamAvoidEdge).where(TeamAvoidEdge.event_id.in_(source_event_ids))  # type: ignore
        ).all() if source_event_ids else []

        source_players = session.exec(
            select(Player).where(Player.tournament_id == tournament_id)
        ).all()
        source_team_players = session.exec(
            select(TeamPlayer).where(TeamPlayer.team_id.in_(source_team_ids))  # type: ignore
        ).all() if source_team_ids else []

        source_version_ids = [v.id for v in source_versions if v.id is not None]

        source_assignments = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id.in_(source_version_ids)  # type: ignore
            )
        ).all() if source_version_ids else []
        source_match_locks = session.exec(
            select(MatchLock).where(
                MatchLock.schedule_version_id.in_(source_version_ids)  # type: ignore
            )
        ).all() if source_version_ids else []
        source_slot_locks = session.exec(
            select(SlotLock).where(
                SlotLock.schedule_version_id.in_(source_version_ids)  # type: ignore
            )
        ).all() if source_version_ids else []
        source_policy_runs = session.exec(
            select(PolicyRun).where(
                PolicyRun.schedule_version_id.in_(source_version_ids)  # type: ignore
            )
        ).all() if source_version_ids else []

        # 2) Copy day/time-window metadata.
        for day in source_days:
            session.add(
                TournamentDay(
                    tournament_id=new_tournament.id,  # type: ignore[arg-type]
                    date=day.date,
                    is_active=day.is_active,
                    start_time=day.start_time,
                    end_time=day.end_time,
                    courts_available=day.courts_available,
                )
            )
        for window in source_windows:
            session.add(
                TournamentTimeWindow(
                    tournament_id=new_tournament.id,  # type: ignore[arg-type]
                    day_date=window.day_date,
                    start_time=window.start_time,
                    end_time=window.end_time,
                    courts_available=window.courts_available,
                    block_minutes=window.block_minutes,
                    label=window.label,
                    is_active=window.is_active,
                )
            )

        # 3) Copy event + team graph.
        event_id_map: dict[int, int] = {}
        for event in source_events:
            if event.id is None:
                continue
            cloned = Event(
                tournament_id=new_tournament.id,  # type: ignore[arg-type]
                category=event.category,
                name=event.name,
                team_count=event.team_count,
                notes=event.notes,
                draw_plan_json=event.draw_plan_json,
                draw_plan_version=event.draw_plan_version,
                draw_status=event.draw_status,
                wf_block_minutes=event.wf_block_minutes,
                standard_block_minutes=event.standard_block_minutes,
                guarantee_selected=event.guarantee_selected,
                schedule_profile_json=event.schedule_profile_json,
            )
            session.add(cloned)
            session.flush()
            event_id_map[event.id] = cloned.id  # type: ignore[index]

        team_id_map: dict[int, int] = {}
        for team in source_teams:
            if team.id is None:
                continue
            mapped_event_id = event_id_map.get(team.event_id)
            if mapped_event_id is None:
                continue
            cloned = Team(
                event_id=mapped_event_id,
                name=team.name,
                seed=team.seed,
                rating=team.rating,
                registration_timestamp=team.registration_timestamp,
                wf_group_index=team.wf_group_index,
                avoid_group=team.avoid_group,
                display_name=team.display_name,
                player1_cellphone=team.player1_cellphone,
                player1_email=team.player1_email,
                player2_cellphone=team.player2_cellphone,
                player2_email=team.player2_email,
                p1_cell=team.p1_cell,
                p1_email=team.p1_email,
                p2_cell=team.p2_cell,
                p2_email=team.p2_email,
                is_defaulted=team.is_defaulted,
                notes=team.notes,
                created_at=team.created_at,
            )
            session.add(cloned)
            session.flush()
            team_id_map[team.id] = cloned.id  # type: ignore[index]

        for edge in source_avoid_edges:
            mapped_event_id = event_id_map.get(edge.event_id)
            mapped_a = team_id_map.get(edge.team_id_a)
            mapped_b = team_id_map.get(edge.team_id_b)
            if mapped_event_id is None or mapped_a is None or mapped_b is None:
                continue
            session.add(
                TeamAvoidEdge(
                    event_id=mapped_event_id,
                    team_id_a=min(mapped_a, mapped_b),
                    team_id_b=max(mapped_a, mapped_b),
                    reason=edge.reason,
                    created_at=edge.created_at,
                )
            )

        # 4) Copy player/contact graph used by SMS/player targeting.
        player_id_map: dict[int, int] = {}
        for player in source_players:
            if player.id is None:
                continue
            cloned = Player(
                tournament_id=new_tournament.id,  # type: ignore[arg-type]
                full_name=player.full_name,
                display_name=player.display_name,
                phone_e164=player.phone_e164,
                email=player.email,
                sms_consent_status=player.sms_consent_status,
                sms_consent_source=player.sms_consent_source,
                sms_consent_updated_at=player.sms_consent_updated_at,
                sms_consented_at=player.sms_consented_at,
                sms_opted_out_at=player.sms_opted_out_at,
                created_at=player.created_at,
                updated_at=player.updated_at,
            )
            session.add(cloned)
            session.flush()
            player_id_map[player.id] = cloned.id  # type: ignore[index]

        for link in source_team_players:
            mapped_team_id = team_id_map.get(link.team_id)
            mapped_player_id = player_id_map.get(link.player_id)
            if mapped_team_id is None or mapped_player_id is None:
                continue
            session.add(
                TeamPlayer(
                    team_id=mapped_team_id,
                    player_id=mapped_player_id,
                    lineup_slot=link.lineup_slot,
                    role=link.role,
                    is_primary_contact=link.is_primary_contact,
                    created_at=link.created_at,
                    updated_at=link.updated_at,
                )
            )

        # 5) Copy schedule graph (versions -> slots/matches -> assignments/locks).
        version_id_map: dict[int, int] = {}
        for version in source_versions:
            if version.id is None:
                continue
            cloned = ScheduleVersion(
                tournament_id=new_tournament.id,  # type: ignore[arg-type]
                version_number=version.version_number,
                status=version.status,
                created_at=version.created_at,
                created_by=version.created_by,
                notes=version.notes,
                finalized_at=version.finalized_at,
                finalized_checksum=version.finalized_checksum,
            )
            session.add(cloned)
            session.flush()
            version_id_map[version.id] = cloned.id  # type: ignore[index]

        slot_id_map: dict[int, int] = {}
        for slot in source_slots:
            if slot.id is None:
                continue
            mapped_version_id = version_id_map.get(slot.schedule_version_id)
            if mapped_version_id is None:
                continue
            cloned = ScheduleSlot(
                tournament_id=new_tournament.id,  # type: ignore[arg-type]
                schedule_version_id=mapped_version_id,
                day_date=slot.day_date,
                start_time=slot.start_time,
                end_time=slot.end_time,
                court_number=slot.court_number,
                court_label=slot.court_label,
                block_minutes=slot.block_minutes,
                label=slot.label,
                is_active=slot.is_active,
            )
            session.add(cloned)
            session.flush()
            slot_id_map[slot.id] = cloned.id  # type: ignore[index]

        match_id_map: dict[int, int] = {}
        pending_match_source_links: List[tuple[Match, Optional[int], Optional[int]]] = []
        for match in source_matches:
            if match.id is None:
                continue
            mapped_event_id = event_id_map.get(match.event_id)
            mapped_version_id = version_id_map.get(match.schedule_version_id)
            if mapped_event_id is None or mapped_version_id is None:
                continue
            cloned = Match(
                tournament_id=new_tournament.id,  # type: ignore[arg-type]
                event_id=mapped_event_id,
                schedule_version_id=mapped_version_id,
                match_code=match.match_code,
                match_type=match.match_type,
                round_number=match.round_number,
                round_index=match.round_index,
                sequence_in_round=match.sequence_in_round,
                duration_minutes=match.duration_minutes,
                consolation_tier=match.consolation_tier,
                placement_type=match.placement_type,
                team_a_id=team_id_map.get(match.team_a_id) if match.team_a_id else None,
                team_b_id=team_id_map.get(match.team_b_id) if match.team_b_id else None,
                placeholder_side_a=match.placeholder_side_a,
                placeholder_side_b=match.placeholder_side_b,
                preferred_day=match.preferred_day,
                source_match_a_id=None,
                source_match_b_id=None,
                source_a_role=match.source_a_role,
                source_b_role=match.source_b_role,
                status=match.status,
                created_at=match.created_at,
                runtime_status=match.runtime_status,
                score_json=match.score_json,
                winner_team_id=team_id_map.get(match.winner_team_id) if match.winner_team_id else None,
                started_at=match.started_at,
                completed_at=match.completed_at,
            )
            session.add(cloned)
            session.flush()
            match_id_map[match.id] = cloned.id  # type: ignore[index]
            pending_match_source_links.append((cloned, match.source_match_a_id, match.source_match_b_id))

        for cloned_match, old_a_id, old_b_id in pending_match_source_links:
            cloned_match.source_match_a_id = match_id_map.get(old_a_id) if old_a_id else None
            cloned_match.source_match_b_id = match_id_map.get(old_b_id) if old_b_id else None
            session.add(cloned_match)

        for assignment in source_assignments:
            mapped_version_id = version_id_map.get(assignment.schedule_version_id)
            mapped_match_id = match_id_map.get(assignment.match_id)
            mapped_slot_id = slot_id_map.get(assignment.slot_id)
            if mapped_version_id is None or mapped_match_id is None or mapped_slot_id is None:
                continue
            session.add(
                MatchAssignment(
                    schedule_version_id=mapped_version_id,
                    match_id=mapped_match_id,
                    slot_id=mapped_slot_id,
                    assigned_at=assignment.assigned_at,
                    assigned_by=assignment.assigned_by,
                    locked=assignment.locked,
                )
            )

        for lock in source_match_locks:
            mapped_version_id = version_id_map.get(lock.schedule_version_id)
            mapped_match_id = match_id_map.get(lock.match_id)
            mapped_slot_id = slot_id_map.get(lock.slot_id)
            if mapped_version_id is None or mapped_match_id is None or mapped_slot_id is None:
                continue
            session.add(
                MatchLock(
                    schedule_version_id=mapped_version_id,
                    match_id=mapped_match_id,
                    slot_id=mapped_slot_id,
                    created_at=lock.created_at,
                    created_by=lock.created_by,
                )
            )

        for lock in source_slot_locks:
            mapped_version_id = version_id_map.get(lock.schedule_version_id)
            mapped_slot_id = slot_id_map.get(lock.slot_id)
            if mapped_version_id is None or mapped_slot_id is None:
                continue
            session.add(
                SlotLock(
                    schedule_version_id=mapped_version_id,
                    slot_id=mapped_slot_id,
                    status=lock.status,
                    created_at=lock.created_at,
                )
            )

        for run in source_policy_runs:
            mapped_version_id = version_id_map.get(run.schedule_version_id)
            if mapped_version_id is None:
                continue
            session.add(
                PolicyRun(
                    tournament_id=new_tournament.id,  # type: ignore[arg-type]
                    schedule_version_id=mapped_version_id,
                    day_date=run.day_date,
                    policy_version=run.policy_version,
                    created_at=run.created_at,
                    input_hash=run.input_hash,
                    output_hash=run.output_hash,
                    ok=run.ok,
                    total_assigned=run.total_assigned,
                    total_failed=run.total_failed,
                    total_reserved_spares=run.total_reserved_spares,
                    duration_ms=run.duration_ms,
                    snapshot_json=run.snapshot_json,
                )
            )

        # 6) Copy desk/UI state and SMS config artifacts.
        for row in source_court_state:
            session.add(
                TournamentCourtState(
                    tournament_id=new_tournament.id,  # type: ignore[arg-type]
                    court_label=row.court_label,
                    is_closed=row.is_closed,
                    note=row.note,
                    updated_at=row.updated_at,
                )
            )

        if source_sms_settings:
            session.add(
                TournamentSmsSettings(
                    tournament_id=new_tournament.id,  # type: ignore[arg-type]
                    auto_first_match=source_sms_settings.auto_first_match,
                    auto_post_match_next=source_sms_settings.auto_post_match_next,
                    auto_on_deck=source_sms_settings.auto_on_deck,
                    auto_up_next=source_sms_settings.auto_up_next,
                    auto_court_change=source_sms_settings.auto_court_change,
                    test_mode=source_sms_settings.test_mode,
                    test_allowlist=source_sms_settings.test_allowlist,
                    player_contacts_only=source_sms_settings.player_contacts_only,
                    created_at=source_sms_settings.created_at,
                    updated_at=source_sms_settings.updated_at,
                )
            )

        for template in source_sms_templates:
            session.add(
                SmsTemplate(
                    tournament_id=new_tournament.id,  # type: ignore[arg-type]
                    message_type=template.message_type,
                    template_body=template.template_body,
                    is_active=template.is_active,
                    created_at=template.created_at,
                    updated_at=template.updated_at,
                )
            )

        # Preserve the source tournament's public version pointer if possible.
        source_public_version_id = source_tournament.public_schedule_version_id
        if source_public_version_id is not None:
            new_tournament.public_schedule_version_id = version_id_map.get(source_public_version_id)
            session.add(new_tournament)

        session.commit()
        session.refresh(new_tournament)

        return new_tournament
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to duplicate tournament: {str(e)}")


@router.delete("/tournaments/{tournament_id}", status_code=204)
def delete_tournament(tournament_id: int, session: Session = Depends(get_session)):
    """Delete a tournament and all its related data (events, days, time windows, etc.)"""
    try:
        # Check if tournament exists (without loading it into session to avoid relationship handling)
        tournament_exists = session.exec(select(func.count(Tournament.id)).where(Tournament.id == tournament_id)).one()

        if tournament_exists == 0:
            raise HTTPException(status_code=404, detail="Tournament not found")

        # Delete related records using raw SQL to completely bypass SQLAlchemy ORM
        # This prevents any relationship handling or tracking
        # Using parameterized queries to prevent SQL injection
        # Order matters: delete child records before parent records

        # 1. Delete events (and their related data will be cascade deleted if configured)
        session.execute(
            text("DELETE FROM event WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )

        # 2. Delete time windows using raw SQL
        session.execute(
            text("DELETE FROM tournamenttimewindow WHERE tournament_id = :tournament_id"),
            {"tournament_id": tournament_id},
        )

        # 3. Delete tournament days using raw SQL
        session.execute(
            text("DELETE FROM tournamentday WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )

        # 4. Delete schedule-related data (if any exists)
        # Schedule versions, slots, matches, assignments
        session.execute(
            text(
                "DELETE FROM matchassignment WHERE schedule_version_id IN (SELECT id FROM scheduleversion WHERE tournament_id = :tournament_id)"
            ),
            {"tournament_id": tournament_id},
        )
        session.execute(
            text("DELETE FROM match WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )
        session.execute(
            text("DELETE FROM scheduleslot WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )
        session.execute(
            text("DELETE FROM scheduleversion WHERE tournament_id = :tournament_id"), {"tournament_id": tournament_id}
        )

        # 5. Delete the tournament itself using raw SQL
        session.execute(text("DELETE FROM tournament WHERE id = :tournament_id"), {"tournament_id": tournament_id})

        session.commit()

        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete tournament: {str(e)}")
