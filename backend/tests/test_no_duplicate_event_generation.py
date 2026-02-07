"""
Tests for preventing duplicate match generation.

Verifies:
- Events are not duplicated in the generation list
- No duplicate match_codes are generated
- Build Schedule is safe to call multiple times
- No UNIQUE constraint errors occur
"""

import json
import pytest
from datetime import date, time
from sqlmodel import Session, select, func

from app.database import engine
from app.models.event import Event
from app.models.match import Match
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.models.tournament_time_window import TournamentTimeWindow
from app.services.schedule_orchestrator import build_schedule_v1


@pytest.fixture
def multi_event_setup():
    """Set up a tournament with multiple events to test duplicate prevention."""
    with Session(engine) as session:
        # Create tournament
        tournament = Tournament(
            name="Multi-Event Test Tournament",
            location="Test Location",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 3),
            timezone="America/New_York",
            court_names="1,2,3,4,5,6",
            use_time_windows=True,
        )
        session.add(tournament)
        session.flush()

        # Create multiple events with finalized draws
        # Use RR_ONLY template which is simplest and most reliable for testing
        events = []
        all_teams = []
        for i, (name, team_count) in enumerate([
            ("Mixed Doubles", 4),
            ("Women's A", 6),
            ("Women's B", 4),
        ]):
            event = Event(
                tournament_id=tournament.id,
                name=name,
                category="mixed" if "Mixed" in name else "women",
                team_count=team_count,
                draw_status="final",
                draw_plan_json=json.dumps({
                    "version": "1.0",
                    "template_type": "RR_ONLY",
                    "wf_rounds": 0,
                }),
                waterfall_match_length=60,
                standard_match_length=105,
            )
            session.add(event)
            session.flush()  # Get event.id
            
            # Create teams for this event
            for t in range(team_count):
                team = Team(
                    event_id=event.id,
                    name=f"{name} Team {t+1}",
                    seed=t + 1,
                )
                session.add(team)
                all_teams.append(team)
            
            events.append(event)
        session.flush()

        # Create time windows with enough capacity
        # Use block_minutes=105 to match standard_match_length for RR_ONLY matches
        for day_offset in range(3):
            window = TournamentTimeWindow(
                tournament_id=tournament.id,
                day_date=date(2026, 5, 1 + day_offset),
                start_time=time(8, 0),
                end_time=time(18, 0),
                block_minutes=105,
                courts_available=6,
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
            "event_ids": [e.id for e in events],
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
        for w in session.exec(select(TournamentTimeWindow).where(TournamentTimeWindow.tournament_id == tournament.id)).all():
            session.delete(w)
        session.delete(version)
        for t in all_teams:
            session.delete(t)
        for e in events:
            session.delete(e)
        session.delete(tournament)
        session.commit()


class TestNoDuplicateEventGeneration:
    """Tests for duplicate match generation prevention."""

    def test_no_duplicate_match_codes_on_build(self, multi_event_setup):
        """Build Schedule should generate unique match codes for all events."""
        setup = multi_event_setup

        with Session(engine) as session:
            # Build schedule
            result = build_schedule_v1(
                session=session,
                tournament_id=setup["tournament_id"],
                version_id=setup["version_id"],
                clear_existing=True,
                inject_teams=False,
            )

            # Verify build succeeded
            assert result.summary.matches_generated > 0, "No matches generated"

            # Get all match codes
            matches = session.exec(
                select(Match).where(Match.schedule_version_id == setup["version_id"])
            ).all()
            match_codes = [m.match_code for m in matches]

            # Verify no duplicates
            unique_codes = set(match_codes)
            assert len(unique_codes) == len(match_codes), (
                f"Duplicate match_codes detected: {[c for c in match_codes if match_codes.count(c) > 1]}"
            )

    def test_rebuild_does_not_create_duplicates(self, multi_event_setup):
        """Rebuilding schedule should not create duplicate matches."""
        setup = multi_event_setup

        with Session(engine) as session:
            # First build
            result1 = build_schedule_v1(
                session=session,
                tournament_id=setup["tournament_id"],
                version_id=setup["version_id"],
                clear_existing=True,
            )
            count1 = result1.summary.matches_generated

            # Get match codes after first build
            matches1 = session.exec(
                select(Match).where(Match.schedule_version_id == setup["version_id"]).order_by(Match.id)
            ).all()
            codes1 = [m.match_code for m in matches1]

            # Second build (should not generate new matches)
            result2 = build_schedule_v1(
                session=session,
                tournament_id=setup["tournament_id"],
                version_id=setup["version_id"],
                clear_existing=True,
            )
            count2 = result2.summary.matches_generated

            # Get match codes after second build
            matches2 = session.exec(
                select(Match).where(Match.schedule_version_id == setup["version_id"]).order_by(Match.id)
            ).all()
            codes2 = [m.match_code for m in matches2]

            # Assertions
            assert count1 == count2, f"Match count changed: {count1} -> {count2}"
            assert codes1 == codes2, "Match codes changed after rebuild"
            assert len(set(codes2)) == len(codes2), "Duplicate match_codes after rebuild"

    def test_each_event_processed_exactly_once(self, multi_event_setup):
        """Each event should have matches generated exactly once."""
        setup = multi_event_setup

        with Session(engine) as session:
            # Build schedule
            build_schedule_v1(
                session=session,
                tournament_id=setup["tournament_id"],
                version_id=setup["version_id"],
                clear_existing=True,
            )

            # Count matches per event
            for event_id in setup["event_ids"]:
                count = session.exec(
                    select(func.count(Match.id)).where(
                        Match.schedule_version_id == setup["version_id"],
                        Match.event_id == event_id,
                    )
                ).scalar_one()

                # Get event details for assertion message
                event = session.get(Event, event_id)

                # Each event should have at least one match
                assert count > 0, f"Event {event.name} (id={event_id}) has no matches"

                # Verify match codes for this event are unique
                event_matches = session.exec(
                    select(Match).where(
                        Match.schedule_version_id == setup["version_id"],
                        Match.event_id == event_id,
                    )
                ).all()
                event_codes = [m.match_code for m in event_matches]
                unique_event_codes = set(event_codes)
                
                assert len(unique_event_codes) == len(event_codes), (
                    f"Event {event.name} has duplicate match_codes: "
                    f"{[c for c in event_codes if event_codes.count(c) > 1]}"
                )

    def test_no_integrity_error_on_triple_build(self, multi_event_setup):
        """Building schedule three times should never raise IntegrityError."""
        setup = multi_event_setup

        with Session(engine) as session:
            # Build 1
            result1 = build_schedule_v1(
                session=session,
                tournament_id=setup["tournament_id"],
                version_id=setup["version_id"],
                clear_existing=True,
            )

            # Build 2
            result2 = build_schedule_v1(
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

            # All should complete without error
            assert result1.summary.matches_generated > 0
            assert result2.summary.matches_generated == result1.summary.matches_generated
            assert result3.summary.matches_generated == result1.summary.matches_generated

            # Verify final state is correct
            final_count = session.exec(
                select(func.count(Match.id)).where(Match.schedule_version_id == setup["version_id"])
            ).scalar_one()
            assert final_count == result1.summary.matches_generated
