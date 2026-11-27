"""Unavailable courts can be opened for one tournament day and restored."""

from datetime import date, time

from sqlmodel import Session, select

from app.models.court_availability_override import CourtAvailabilityOverride
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.services.score_parser import scoring_mode_for_match_type, score_supports_winner


def test_scoring_format_follows_the_draw_not_the_day():
    assert scoring_mode_for_match_type("WF", "MIX_E16_WF_R1_01") == "PRO_SET_8"
    assert scoring_mode_for_match_type("MAIN", "MIX_E16_WF_R2_W01") == "PRO_SET_8"
    assert scoring_mode_for_match_type("MAIN", "MIX_E16_BWW_M1") == "REGULAR"
    assert scoring_mode_for_match_type("RR", "MIX_E16_RR_A_1") == "REGULAR"
    assert score_supports_winner("8-3", team_a_wins=False)
    assert score_supports_winner("6-4, 6-3", team_a_wins=False)
    assert score_supports_winner("6-4, 3-6, 1-0", team_a_wins=False)
    assert score_supports_winner("3-6, 6-4, 1-0", team_a_wins=True)
    assert not score_supports_winner("3-8", team_a_wins=False)
    assert not score_supports_winner("4-8", team_a_wins=True)


def test_unavailable_court_override_is_persistent_and_restorable(client, session: Session):
    tournament = Tournament(
        name="Availability Copy",
        location="Test",
        timezone="America/Chicago",
        start_date=date(2026, 4, 3),
        end_date=date(2026, 4, 5),
    )
    session.add(tournament)
    session.flush()
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.flush()
    day = date(2026, 4, 3)
    opened = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=day,
        start_time=time(8, 0),
        end_time=time(9, 0),
        court_number=2,
        court_label="2",
        block_minutes=60,
        is_active=False,
    )
    other = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=day,
        start_time=time(8, 0),
        end_time=time(9, 0),
        court_number=4,
        court_label="4",
        block_minutes=60,
        is_active=False,
    )
    session.add(opened)
    session.add(other)
    session.commit()

    made = client.post(
        f"/api/desk/tournaments/{tournament.id}/court-availability",
        json={
            "version_id": version.id,
            "day_date": "2026-04-03",
            "court_number": 2,
            "scope": "slot",
            "start_time": "08:00",
        },
    )
    assert made.status_code == 200, made.text
    snap = client.get(f"/api/desk/tournaments/{tournament.id}/snapshot?version_id={version.id}").json()
    court_two = next(slot for slot in snap["slots"] if slot["court_number"] == 2)
    court_four = next(slot for slot in snap["slots"] if slot["court_number"] == 4)
    assert court_two["is_active"] is True
    assert court_two["scheduled_active"] is False
    assert court_four["is_active"] is False

    event = Event(tournament_id=tournament.id, category="mixed", name="Mixed", team_count=2)
    session.add(event)
    session.flush()
    match = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="TEST_RR_1",
        match_type="RR",
        round_number=1,
        sequence_in_round=1,
        duration_minutes=90,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="SCHEDULED",
    )
    session.add(match)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=version.id, match_id=match.id, slot_id=opened.id))
    session.commit()

    blocked = client.post(
        f"/api/desk/tournaments/{tournament.id}/court-availability/restore",
        json={"version_id": version.id, "day_date": "2026-04-03", "court_number": 2},
    )
    assert blocked.status_code == 409
    assert "Move or finish" in blocked.json()["detail"]

    session.delete(session.exec(select(MatchAssignment).where(MatchAssignment.match_id == match.id)).one())
    session.commit()
    restored = client.post(
        f"/api/desk/tournaments/{tournament.id}/court-availability/restore",
        json={"version_id": version.id, "day_date": "2026-04-03", "court_number": 2},
    )
    assert restored.status_code == 200, restored.text
    session.expire_all()
    assert session.exec(select(CourtAvailabilityOverride)).all() == []
    stored = session.get(ScheduleSlot, opened.id)
    assert stored.is_active is False
