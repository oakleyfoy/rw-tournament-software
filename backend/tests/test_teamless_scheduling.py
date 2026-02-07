"""
Tests for Policy B: Teamless Scheduling

Verifies that auto-assign can schedule matches with null team IDs
when allow_teamless=True (default for draft schedules).
"""

import pytest
from datetime import date, time
from sqlmodel import Session, select

from app.database import engine
from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.utils.rest_rules import auto_assign_with_rest


@pytest.fixture
def teamless_test_setup():
    """Set up a tournament with matches that have null teams."""
    with Session(engine) as session:
        # Create tournament
        tournament = Tournament(
            name="Teamless Test Tournament",
            location="Test Location",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 3),
            timezone="America/New_York",
            court_names="1,2,3,4,5",
        )
        session.add(tournament)
        session.flush()

        # Create event
        event = Event(
            tournament_id=tournament.id,
            name="Test Event",
            category="mixed",
            team_count=8,
            draw_status="final",
        )
        session.add(event)
        session.flush()

        # Create schedule version
        version = ScheduleVersion(
            tournament_id=tournament.id,
            status="draft",
            version_number=1,
        )
        session.add(version)
        session.flush()

        # Create slots (5 courts x 4 slots each = 20 slots)
        slots = []
        for court in range(1, 6):
            for hour in range(8, 12):
                slot = ScheduleSlot(
                    tournament_id=tournament.id,
                    schedule_version_id=version.id,
                    day_date=date(2026, 3, 1),
                    start_time=time(hour, 0),
                    end_time=time(hour + 1, 0),
                    court_number=court,
                    court_label=str(court),
                    block_minutes=60,
                    is_active=True,
                )
                slots.append(slot)
                session.add(slot)
        session.flush()

        # Create matches with null teams (like RR/pool matches before team assignment)
        matches = []
        for i in range(10):
            match = Match(
                tournament_id=tournament.id,
                event_id=event.id,
                schedule_version_id=version.id,
                match_code=f"TEST_RR_{i+1:02d}",
                match_type="RR",
                round_number=1,
                sequence_in_round=i + 1,
                duration_minutes=60,
                team_a_id=None,  # Null team
                team_b_id=None,  # Null team
                placeholder_side_a=f"TBD {i*2+1}",
                placeholder_side_b=f"TBD {i*2+2}",
            )
            matches.append(match)
            session.add(match)
        session.flush()

        session.commit()

        yield {
            "tournament_id": tournament.id,
            "event_id": event.id,
            "version_id": version.id,
            "match_count": len(matches),
            "slot_count": len(slots),
        }

        # Cleanup
        session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)).all()
        for a in session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)).all():
            session.delete(a)
        for m in session.exec(select(Match).where(Match.schedule_version_id == version.id)).all():
            session.delete(m)
        for s in session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version.id)).all():
            session.delete(s)
        session.delete(version)
        session.delete(event)
        session.delete(tournament)
        session.commit()


class TestTeamlessScheduling:
    """Tests for Policy B teamless scheduling."""

    def test_allow_teamless_true_assigns_all_matches(self, teamless_test_setup):
        """With allow_teamless=True, all matches should be assigned even without teams."""
        setup = teamless_test_setup

        with Session(engine) as session:
            result = auto_assign_with_rest(
                session=session,
                schedule_version_id=setup["version_id"],
                clear_existing=True,
                allow_teamless=True,
            )

            assert result["assigned_count"] == setup["match_count"], (
                f"Expected all {setup['match_count']} matches assigned, got {result['assigned_count']}"
            )
            assert result["unassigned_count"] == 0
            assert result["unknown_team_matches_count"] == setup["match_count"], (
                f"Expected {setup['match_count']} unknown team matches, got {result['unknown_team_matches_count']}"
            )

    def test_allow_teamless_false_skips_teamless_matches(self, teamless_test_setup):
        """With allow_teamless=False, teamless matches without deps should be skipped."""
        setup = teamless_test_setup

        with Session(engine) as session:
            result = auto_assign_with_rest(
                session=session,
                schedule_version_id=setup["version_id"],
                clear_existing=True,
                allow_teamless=False,
            )

            assert result["assigned_count"] == 0, (
                f"Expected 0 matches assigned in strict mode, got {result['assigned_count']}"
            )
            assert result["unassigned_count"] == setup["match_count"]
            assert "NULL_TEAM" in result["unassigned_reasons"]

    def test_deterministic_assignment_order(self, teamless_test_setup):
        """Assignment order should be deterministic across runs."""
        setup = teamless_test_setup

        with Session(engine) as session:
            # First run
            result1 = auto_assign_with_rest(
                session=session,
                schedule_version_id=setup["version_id"],
                clear_existing=True,
                allow_teamless=True,
            )

            # Get assignments
            assignments1 = session.exec(
                select(MatchAssignment)
                .where(MatchAssignment.schedule_version_id == setup["version_id"])
                .order_by(MatchAssignment.match_id)
            ).all()
            mapping1 = {a.match_id: a.slot_id for a in assignments1}

            # Second run (clear and reassign)
            result2 = auto_assign_with_rest(
                session=session,
                schedule_version_id=setup["version_id"],
                clear_existing=True,
                allow_teamless=True,
            )

            # Get assignments again
            assignments2 = session.exec(
                select(MatchAssignment)
                .where(MatchAssignment.schedule_version_id == setup["version_id"])
                .order_by(MatchAssignment.match_id)
            ).all()
            mapping2 = {a.match_id: a.slot_id for a in assignments2}

            # Verify deterministic
            assert mapping1 == mapping2, "Assignment order should be deterministic"
            assert result1["assigned_count"] == result2["assigned_count"]
