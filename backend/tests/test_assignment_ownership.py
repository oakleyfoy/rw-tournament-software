"""Cross-tournament assignment ownership guards."""

from datetime import date, time

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event, EventCategory
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.services.assignment_ownership import AssignmentOwnershipError, create_owned_assignment
from app.services.schedule_sequence import build_master_sequence, run_sequence_schedule


def _tournament(session: Session, name: str) -> Tournament:
    tournament = Tournament(
        name=name,
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 9, 11),
        end_date=date(2026, 9, 13),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    return tournament


def _version(session: Session, tournament_id: int) -> ScheduleVersion:
    version = ScheduleVersion(tournament_id=tournament_id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def _event(session: Session, tournament_id: int, name: str) -> Event:
    event = Event(
        tournament_id=tournament_id,
        name=name,
        category=EventCategory.womens,
        team_count=8,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _match(
    session: Session,
    *,
    tournament_id: int,
    event_id: int,
    version_id: int,
    code: str,
) -> Match:
    match = Match(
        tournament_id=tournament_id,
        event_id=event_id,
        schedule_version_id=version_id,
        match_code=code,
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="A",
        placeholder_side_b="B",
        status="unscheduled",
    )
    session.add(match)
    session.commit()
    session.refresh(match)
    return match


def _slot(session: Session, *, tournament_id: int, version_id: int, court: int = 1) -> ScheduleSlot:
    slot = ScheduleSlot(
        tournament_id=tournament_id,
        schedule_version_id=version_id,
        day_date=date(2026, 9, 11),
        start_time=time(9, 30),
        end_time=time(10, 30),
        court_number=court,
        court_label=str(court),
        block_minutes=60,
        is_active=True,
    )
    session.add(slot)
    session.commit()
    session.refresh(slot)
    return slot


def test_a_sequence_skips_foreign_match_on_same_version(session: Session):
    tournament_a = _tournament(session, "Tournament A")
    tournament_b = _tournament(session, "Tournament B")
    version_a = _version(session, tournament_a.id)
    event_a = _event(session, tournament_a.id, "Women's A")
    event_b = _event(session, tournament_b.id, "Foreign Event")
    owned = _match(
        session,
        tournament_id=tournament_a.id,
        event_id=event_a.id,
        version_id=version_a.id,
        code="OWNED_WF_01",
    )
    foreign = _match(
        session,
        tournament_id=tournament_b.id,
        event_id=event_b.id,
        version_id=version_a.id,
        code="FOREIGN_WF_01",
    )
    slot = _slot(session, tournament_id=tournament_a.id, version_id=version_a.id)

    sequence = build_master_sequence(session, version_a.id, tournament_id=tournament_a.id)
    sequenced_ids = {rm.match_id for rm in sequence}

    assert owned.id in sequenced_ids
    assert foreign.id not in sequenced_ids

    result = run_sequence_schedule(session, tournament_a.id, version_a.id)
    session.commit()
    assigned_ids = {
        a.match_id
        for a in session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version_a.id)).all()
    }
    assert result.total_assigned == 1
    assert assigned_ids == {owned.id}
    assert slot.id is not None


def test_b_manual_assignment_rejects_foreign_match(client: TestClient, session: Session):
    tournament_a = _tournament(session, "Assign A")
    tournament_b = _tournament(session, "Assign B")
    version_a = _version(session, tournament_a.id)
    event_b = _event(session, tournament_b.id, "B Event")
    foreign = _match(
        session,
        tournament_id=tournament_b.id,
        event_id=event_b.id,
        version_id=version_a.id,
        code="FOREIGN_MANUAL",
    )
    slot = _slot(session, tournament_id=tournament_a.id, version_id=version_a.id)

    response = client.post(
        f"/api/tournaments/{tournament_a.id}/schedule/assignments",
        json={
            "schedule_version_id": version_a.id,
            "match_id": foreign.id,
            "slot_id": slot.id,
        },
    )
    assert response.status_code == 400
    assert "ownership mismatch" in response.json()["detail"]
    assert session.exec(select(MatchAssignment)).all() == []


def test_c_valid_assignment_succeeds(client: TestClient, session: Session):
    tournament = _tournament(session, "Assign Valid")
    version = _version(session, tournament.id)
    event = _event(session, tournament.id, "Women's A")
    match = _match(
        session,
        tournament_id=tournament.id,
        event_id=event.id,
        version_id=version.id,
        code="VALID_WF_01",
    )
    slot = _slot(session, tournament_id=tournament.id, version_id=version.id)

    response = client.post(
        f"/api/tournaments/{tournament.id}/schedule/assignments",
        json={
            "schedule_version_id": version.id,
            "match_id": match.id,
            "slot_id": slot.id,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["match_id"] == match.id
    assert body["slot_id"] == slot.id
    assert body["schedule_version_id"] == version.id

    created = session.exec(select(MatchAssignment)).all()
    assert len(created) == 1
    assert created[0].match_id == match.id


def test_c_helper_valid_assignment_unchanged(session: Session):
    tournament = _tournament(session, "Helper Valid")
    version = _version(session, tournament.id)
    event = _event(session, tournament.id, "Women's A")
    match = _match(
        session,
        tournament_id=tournament.id,
        event_id=event.id,
        version_id=version.id,
        code="HELPER_WF_01",
    )
    slot = _slot(session, tournament_id=tournament.id, version_id=version.id)

    assignment = create_owned_assignment(
        session,
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        match_id=match.id,
        slot_id=slot.id,
        assigned_by="TEST",
    )
    session.commit()
    assert assignment.id is not None
    assert assignment.match_id == match.id
    assert assignment.slot_id == slot.id


def test_c_helper_rejects_foreign_without_writing(session: Session):
    tournament_a = _tournament(session, "Helper A")
    tournament_b = _tournament(session, "Helper B")
    version_a = _version(session, tournament_a.id)
    event_b = _event(session, tournament_b.id, "Foreign")
    foreign = _match(
        session,
        tournament_id=tournament_b.id,
        event_id=event_b.id,
        version_id=version_a.id,
        code="HELPER_FOREIGN",
    )
    slot = _slot(session, tournament_id=tournament_a.id, version_id=version_a.id)

    try:
        create_owned_assignment(
            session,
            tournament_id=tournament_a.id,
            schedule_version_id=version_a.id,
            match_id=foreign.id,
            slot_id=slot.id,
        )
        raised = False
    except AssignmentOwnershipError as exc:
        raised = True
        assert "ownership mismatch" in str(exc)
    assert raised
    session.rollback()
    assert session.exec(select(MatchAssignment)).all() == []


def test_d_grid_excludes_foreign_assignment(client: TestClient, session: Session):
    tournament_a = _tournament(session, "Grid A")
    tournament_b = _tournament(session, "Grid B")
    version_a = _version(session, tournament_a.id)
    event_a = _event(session, tournament_a.id, "Women's A")
    event_b = _event(session, tournament_b.id, "Foreign Grid")
    owned = _match(
        session,
        tournament_id=tournament_a.id,
        event_id=event_a.id,
        version_id=version_a.id,
        code="GRID_OWNED",
    )
    foreign = _match(
        session,
        tournament_id=tournament_b.id,
        event_id=event_b.id,
        version_id=version_a.id,
        code="GRID_FOREIGN",
    )
    slot_owned = _slot(session, tournament_id=tournament_a.id, version_id=version_a.id, court=1)
    slot_foreign = _slot(session, tournament_id=tournament_a.id, version_id=version_a.id, court=2)

    session.add(
        MatchAssignment(
            schedule_version_id=version_a.id,
            match_id=owned.id,
            slot_id=slot_owned.id,
            assigned_by="test",
        )
    )
    session.add(
        MatchAssignment(
            schedule_version_id=version_a.id,
            match_id=foreign.id,
            slot_id=slot_foreign.id,
            assigned_by="corrupt",
        )
    )
    session.commit()

    response = client.get(
        f"/api/tournaments/{tournament_a.id}/schedule/grid",
        params={"schedule_version_id": version_a.id},
    )
    assert response.status_code == 200
    data = response.json()
    match_ids = {m["match_id"] for m in data["matches"]}
    assigned_match_ids = {a["match_id"] for a in data["assignments"]}
    assert owned.id in match_ids
    assert foreign.id not in match_ids
    assert assigned_match_ids == {owned.id}
    assert data["ownership_issues"]
    assert any("ownership mismatch" in issue for issue in data["ownership_issues"])


def test_e_public_schedule_excludes_foreign_match(client: TestClient, session: Session):
    tournament_a = _tournament(session, "Public A")
    tournament_b = _tournament(session, "Public B")
    version_a = _version(session, tournament_a.id)
    version_a.status = "final"
    session.add(version_a)
    event_a = _event(session, tournament_a.id, "Women's A")
    event_b = _event(session, tournament_b.id, "Foreign Public")
    owned = _match(
        session,
        tournament_id=tournament_a.id,
        event_id=event_a.id,
        version_id=version_a.id,
        code="PUB_OWNED",
    )
    foreign = _match(
        session,
        tournament_id=tournament_b.id,
        event_id=event_b.id,
        version_id=version_a.id,
        code="PUB_FOREIGN",
    )
    slot = _slot(session, tournament_id=tournament_a.id, version_id=version_a.id)
    session.add(MatchAssignment(schedule_version_id=version_a.id, match_id=owned.id, slot_id=slot.id))
    tournament_a.public_schedule_version_id = version_a.id
    session.add(tournament_a)
    session.commit()

    response = client.get(f"/api/public/tournaments/{tournament_a.id}/schedule")
    assert response.status_code == 200
    data = response.json()
    ids = {m["match_id"] for m in data["matches"]}
    assert owned.id in ids
    assert foreign.id not in ids
