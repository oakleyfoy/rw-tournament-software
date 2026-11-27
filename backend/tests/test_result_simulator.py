"""Time-slot result simulation stays on duplicated test tournaments and uses finalize."""

import random
from datetime import date, time

import pytest
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.sms_log import SmsLog
from app.models.team import Team
from app.models.tournament import Tournament
from app.services.court_assignment_mode import MODE_PREASSIGNED, replace_court_assignment_modes
from app.services.dashboard_progression import start_day
from app.services.result_simulator import advance_to_next_slot, simulation_allowed, simulate_time_slot
from app.services.score_parser import random_valid_score_for_match_type, validate_score_for_match_type


def test_random_scores_follow_the_match_type_and_the_chosen_winner():
    rng = random.Random(4)
    for match_type in ("WF", "MAIN", "RR"):
        for team_a_wins in (True, False):
            for _ in range(12):
                score = random_valid_score_for_match_type(match_type, team_a_wins=team_a_wins, rng=rng)
                ok, message = validate_score_for_match_type(score, match_type)
                assert ok, message
                if match_type == "WF":
                    assert "," not in score
                else:
                    assert "," in score
                first = score.split(",")[0].strip()
                left, right = [int(part) for part in first.split("-")]
                assert left > right
                assert not score.endswith("0-1")
                assert team_a_wins in (True, False)


def _copy(session: Session, *, name: str, source_id: int | None) -> tuple[Tournament, ScheduleVersion, Event]:
    tournament = Tournament(
        name=name,
        location="Palm",
        timezone="America/Chicago",
        start_date=date(2026, 12, 4),
        end_date=date(2026, 12, 6),
        duplicated_from_tournament_id=source_id,
    )
    session.add(tournament)
    session.flush()
    version = ScheduleVersion(tournament_id=tournament.id, version_number=1, status="draft")
    session.add(version)
    session.flush()
    event = Event(tournament_id=tournament.id, category="womens", name="Women's", team_count=4)
    session.add(event)
    session.flush()
    replace_court_assignment_modes(event, {"2026-12-04": MODE_PREASSIGNED})
    session.add(event)
    session.flush()
    return tournament, version, event


def _team(session: Session, event: Event, name: str, seed: int) -> Team:
    team = Team(event_id=event.id, name=name, display_name=name, seed=seed)
    session.add(team)
    session.flush()
    return team


def _match(session, tournament, version, event, court, start, teams, code, duration=60):
    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=version.id,
        day_date=date(2026, 12, 4),
        start_time=start,
        end_time=time(start.hour + 1, 0),
        court_number=court,
        court_label=str(court),
        block_minutes=duration,
        is_active=True,
    )
    session.add(slot)
    session.flush()
    match = Match(
        tournament_id=tournament.id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code=code,
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=court,
        duration_minutes=duration,
        team_a_id=teams[0].id if teams[0] else None,
        team_b_id=teams[1].id if teams[1] else None,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="SCHEDULED",
    )
    session.add(match)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=version.id, match_id=match.id, slot_id=slot.id, assigned_by="MANUAL"))
    session.flush()
    return match


def test_simulation_requires_a_duplicate_record_not_just_the_name():
    real = Tournament(name="Palm Springs 2026", location="Palm", timezone="UTC", start_date=date(2026, 12, 4), end_date=date(2026, 12, 6))
    renamed = Tournament(name="Palm Springs 2026 (Copy)", location="Palm", timezone="UTC", start_date=date(2026, 12, 4), end_date=date(2026, 12, 6))
    duplicate = Tournament(name="Palm Springs 2026 (Copy)", location="Palm", timezone="UTC", start_date=date(2026, 12, 4), end_date=date(2026, 12, 6), duplicated_from_tournament_id=18)
    assert simulation_allowed(real) is False
    assert simulation_allowed(renamed) is False
    assert simulation_allowed(duplicate) is True


def test_selected_slot_uses_finalize_and_leaves_other_work_alone(session: Session):
    tournament, version, event = _copy(session, name="Palm Springs 2026 (Copy)", source_id=18)
    alpha, beta = _team(session, event, "Alpha", 1), _team(session, event, "Beta", 2)
    gamma, delta = _team(session, event, "Gamma", 3), _team(session, event, "Delta", 4)
    later_a, later_b = _team(session, event, "Later A", 5), _team(session, event, "Later B", 6)
    opening = _match(session, tournament, version, event, 1, time(9, 0), (alpha, beta), "WA_R1")
    finished = _match(session, tournament, version, event, 2, time(9, 0), (gamma, delta), "WA_R2")
    finished.runtime_status = "FINAL"
    finished.winner_team_id = gamma.id
    finished.score_json = {"display": "8-3"}
    session.add(finished)
    unresolved = _match(session, tournament, version, event, 3, time(9, 0), (None, None), "WA_R3")
    later = _match(session, tournament, version, event, 1, time(10, 0), (later_a, later_b), "WA_R4")
    session.commit()
    start_day(session, tournament, version, date(2026, 12, 4))
    session.commit()

    with pytest.raises(ValueError, match="duplicated test tournament"):
        plain, plain_version, plain_event = _copy(session, name="Palm Springs 2026", source_id=None)
        simulate_time_slot(session, plain, plain_version, date(2026, 12, 4), "09:00")

    before_logs = len(session.exec(select(SmsLog)).all())
    summary = simulate_time_slot(session, tournament, version, date(2026, 12, 4), "09:00", rng=random.Random(2))
    session.expire_all()
    assert summary["completed"] == 1
    assert summary["skipped"] == 1
    assert summary["blocked"] == 1
    assert summary["failed"] == 0
    saved = session.get(Match, opening.id)
    assert saved.runtime_status == "FINAL"
    assert saved.winner_team_id in (alpha.id, beta.id)
    assert saved.score_json["display"]
    kept = session.get(Match, finished.id)
    assert kept.score_json["display"] == "8-3"
    assert kept.winner_team_id == gamma.id
    blocked = next(row for row in summary["results"] if row["match_id"] == unresolved.id)
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "Both teams not resolved"
    assert session.get(Match, later.id).runtime_status == "SCHEDULED"
    assert len(session.exec(select(SmsLog)).all()) == before_logs

    again = simulate_time_slot(session, tournament, version, date(2026, 12, 4), "09:00", rng=random.Random(3))
    assert again["completed"] == 0
    assert again["skipped"] == 2
    session.expire_all()
    assert session.get(Match, opening.id).score_json["display"] == saved.score_json["display"]

    early = simulate_time_slot(session, tournament, version, date(2026, 12, 4), "10:00", rng=random.Random(5))
    assert early["completed"] == 0
    assert early["results"][0]["reason"] == "Match not yet active"

    advanced = advance_to_next_slot(session, tournament, version, date(2026, 12, 4), "09:00")
    assert advanced["slot_label"] == "10:00 AM"
    done = simulate_time_slot(session, tournament, version, date(2026, 12, 4), "10:00", rng=random.Random(6))
    assert done["completed"] == 1
    session.expire_all()
    assert session.get(Match, later.id).runtime_status == "FINAL"


def test_real_tournament_route_rejects_simulation(client, session: Session):
    tournament, version, _event = _copy(session, name="Palm Springs 2026", source_id=None)
    session.commit()
    response = client.post(
        f"/api/desk/tournaments/{tournament.id}/simulate-results",
        json={"version_id": version.id, "day_date": "2026-12-04", "slot_time": "09:00"},
    )
    assert response.status_code == 403
