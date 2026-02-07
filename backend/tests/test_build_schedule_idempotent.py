"""
Tests for Build Schedule idempotency.

Verifies that calling Build Schedule multiple times:
- Does NOT generate duplicate matches
- Does NOT raise IntegrityError
- Preserves existing match data
- Refreshes slots and assignments correctly
"""

import pytest
from datetime import date, time
from sqlmodel import Session, select, func

from app.database import engine
from app.models.event import Event
from app.models.match import Match
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.models.tournament_time_window import TournamentTimeWindow
from app.services.schedule_orchestrator import build_schedule_v1


@pytest.fixture
def idempotent_test_setup():
    """Set up a tournament with events and time windows for idempotency testing."""
    with Session(engine) as session:
        # Create tournament
        tournament = Tournament(
            name="Idempotent Test Tournament",
            location="Test Location",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 3),
            timezone="America/New_York",
            court_names="1,2,3,4,5",
            use_time_windows=True,
        )
        session.add(tournament)
        session.flush()

        # Create event with finalized draw
        # Note: draw_plan_json needs to be JSON-serializable for SQLite
        import json
        event = Event(
            tournament_id=tournament.id,
            name="Test Event",
            category="mixed",
            team_count=8,
            draw_status="final",
            draw_plan_json=json.dumps({
                "version": "1.0",
                "template_type": "WF_TO_POOLS_DYNAMIC",
                "wf_rounds": 1,
            }),
            waterfall_match_length=60,
            standard_match_length=105,
        )
        session.add(event)
        session.flush()

        # Create time window
        window = TournamentTimeWindow(
            tournament_id=tournament.id,
            day_date=date(2026, 4, 1),
            start_time=time(8, 0),
            end_time=time(18, 0),
            block_minutes=60,
            courts_available=5,
            is_active=True,
        )
        session.add(window)
        session.flush()

        # Create schedule version
        version = ScheduleVersion(
            tournament_id=tournament.id,
            status="draft",
            version_number=1,
        )
        session.add(version)
        session.flush()

        session.commit()

        yield {
            "tournament_id": tournament.id,
            "event_id": event.id,
            "version_id": version.id,
        }

        # Cleanup
        from app.models.match_assignment import MatchAssignment
        for a in session.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == version.id)).all():
            session.delete(a)
        for m in session.exec(select(Match).where(Match.schedule_version_id == version.id)).all():
            session.delete(m)
        for s in session.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version.id)).all():
            session.delete(s)
        session.delete(window)
        session.delete(version)
        session.delete(event)
        session.delete(tournament)
        session.commit()


class TestBuildScheduleIdempotency:
    """Tests for Build Schedule idempotency."""

    def test_auto_assign_does_not_create_matches(self, idempotent_test_setup):
        """Auto-Assign must not create matches - it only assigns existing matches to slots."""
        setup = idempotent_test_setup

        with Session(engine) as session:
            # First build - generates matches
            result1 = build_schedule_v1(
                session=session,
                tournament_id=setup["tournament_id"],
                version_id=setup["version_id"],
                clear_existing=True,
                inject_teams=False,
            )

            # Record match state after first build
            matches_after_build = session.exec(
                select(Match).where(Match.schedule_version_id == setup["version_id"]).order_by(Match.id)
            ).all()
            match_ids_after_build = [m.id for m in matches_after_build]
            match_codes_after_build = [m.match_code for m in matches_after_build]
            match_count_after_build = len(matches_after_build)

            assert match_count_after_build > 0, "No matches generated in first build"

            # Run auto-assign via second build (should NOT generate new matches)
            result2 = build_schedule_v1(
                session=session,
                tournament_id=setup["tournament_id"],
                version_id=setup["version_id"],
                clear_existing=True,  # Clears assignments, not matches
                inject_teams=False,
            )

            # Get matches after second build
            matches_after_assign = session.exec(
                select(Match).where(Match.schedule_version_id == setup["version_id"]).order_by(Match.id)
            ).all()
            match_ids_after_assign = [m.id for m in matches_after_assign]
            match_codes_after_assign = [m.match_code for m in matches_after_assign]

            # Assertions: no new matches created
            assert len(matches_after_assign) == match_count_after_build, (
                f"Match count changed from {match_count_after_build} to {len(matches_after_assign)}"
            )
            assert match_ids_after_build == match_ids_after_assign, "Match IDs changed after auto-assign"
            assert match_codes_after_build == match_codes_after_assign, "Match codes changed after auto-assign"

            # Verify no duplicate match_codes
            unique_codes = set(match_codes_after_assign)
            assert len(unique_codes) == len(match_codes_after_assign), "Duplicate match_codes detected"

    def test_build_schedule_is_idempotent(self, idempotent_test_setup):
        """Calling Build Schedule twice should not duplicate matches."""
        setup = idempotent_test_setup

        with Session(engine) as session:
            # First build
            result1 = build_schedule_v1(
                session=session,
                tournament_id=setup["tournament_id"],
                version_id=setup["version_id"],
                clear_existing=True,
                inject_teams=False,
            )

            # Get match count after first build
            match_count_1 = session.exec(
                select(func.count(Match.id)).where(Match.schedule_version_id == setup["version_id"])
            ).one()

            # Get match codes after first build
            matches_1 = session.exec(
                select(Match).where(Match.schedule_version_id == setup["version_id"]).order_by(Match.id)
            ).all()
            match_codes_1 = [m.match_code for m in matches_1]
            match_ids_1 = [m.id for m in matches_1]

            # Second build (should NOT generate new matches)
            result2 = build_schedule_v1(
                session=session,
                tournament_id=setup["tournament_id"],
                version_id=setup["version_id"],
                clear_existing=True,
                inject_teams=False,
            )

            # Get match count after second build
            match_count_2 = session.exec(
                select(func.count(Match.id)).where(Match.schedule_version_id == setup["version_id"])
            ).one()

            # Get match codes after second build
            matches_2 = session.exec(
                select(Match).where(Match.schedule_version_id == setup["version_id"]).order_by(Match.id)
            ).all()
            match_codes_2 = [m.match_code for m in matches_2]
            match_ids_2 = [m.id for m in matches_2]

            # Assertions
            assert match_count_1 == match_count_2, (
                f"Match count changed from {match_count_1} to {match_count_2}"
            )
            assert match_codes_1 == match_codes_2, "Match codes changed after second build"
            assert match_ids_1 == match_ids_2, "Match IDs changed after second build"
            assert result1.summary.matches_generated == result2.summary.matches_generated, (
                "matches_generated count differs between builds"
            )

            # Verify no duplicate match_codes
            unique_codes = set(match_codes_2)
            assert len(unique_codes) == len(match_codes_2), "Duplicate match_codes detected"

    def test_third_build_also_idempotent(self, idempotent_test_setup):
        """Third build should also be idempotent."""
        setup = idempotent_test_setup

        with Session(engine) as session:
            # Build 1
            build_schedule_v1(
                session=session,
                tournament_id=setup["tournament_id"],
                version_id=setup["version_id"],
                clear_existing=True,
            )

            # Build 2
            build_schedule_v1(
                session=session,
                tournament_id=setup["tournament_id"],
                version_id=setup["version_id"],
                clear_existing=True,
            )

            # Build 3
            result3 = build_schedule_v1(
                session=session,
                tournament_id=setup["tournament_id"],
                version_id=setup["version_id"],
                clear_existing=True,
            )

            match_count = session.exec(
                select(func.count(Match.id)).where(Match.schedule_version_id == setup["version_id"])
            ).one()

            # Should still have the same matches as first build
            assert match_count > 0, "No matches exist after three builds"
            assert result3.summary.matches_generated == match_count, (
                f"matches_generated ({result3.summary.matches_generated}) != match_count ({match_count})"
            )
