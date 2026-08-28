"""Sequence scheduler honors tournament.event_schedule_day_orders_json."""

import json
from datetime import date

from sqlmodel import Session

from app.models.event import Event, EventCategory
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.services.schedule_sequence import build_master_sequence


def _tournament(session: Session, day_orders: list[list[int]] | None = None) -> Tournament:
    tournament = Tournament(
        name="Sequence Day Orders",
        location="Test",
        timezone="America/New_York",
        start_date=date(2026, 9, 11),
        end_date=date(2026, 9, 13),
    )
    if day_orders is not None:
        tournament.event_schedule_day_orders_json = json.dumps({"day_orders": day_orders})
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


def _event(
    session: Session,
    tournament_id: int,
    name: str,
    *,
    category: EventCategory,
    team_count: int,
    schedule_order: int | None = None,
) -> Event:
    profile = None if schedule_order is None else json.dumps({"schedule_order": schedule_order})
    event = Event(
        tournament_id=tournament_id,
        name=name,
        category=category,
        team_count=team_count,
        schedule_profile_json=profile,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _wf_match(
    session: Session,
    *,
    tournament_id: int,
    event_id: int,
    version_id: int,
    round_index: int,
    seq: int,
) -> Match:
    prefix = f"E{event_id}_WF_R{round_index}_{seq:02d}"
    match = Match(
        tournament_id=tournament_id,
        event_id=event_id,
        schedule_version_id=version_id,
        match_code=prefix,
        match_type="WF",
        round_number=round_index,
        round_index=round_index,
        sequence_in_round=seq,
        duration_minutes=60,
        placeholder_side_a=f"A{event_id}-{round_index}-{seq}",
        placeholder_side_b=f"B{event_id}-{round_index}-{seq}",
        status="unscheduled",
    )
    session.add(match)
    session.commit()
    session.refresh(match)
    return match


def _main_match(
    session: Session,
    *,
    tournament_id: int,
    event_id: int,
    version_id: int,
    round_index: int,
    seq: int,
) -> Match:
    match = Match(
        tournament_id=tournament_id,
        event_id=event_id,
        schedule_version_id=version_id,
        match_code=f"E{event_id}_MAIN_R{round_index}_{seq:02d}",
        match_type="MAIN",
        round_number=round_index,
        round_index=round_index,
        sequence_in_round=seq,
        duration_minutes=90,
        placeholder_side_a=f"A{event_id}-M{round_index}-{seq}",
        placeholder_side_b=f"B{event_id}-M{round_index}-{seq}",
        status="unscheduled",
    )
    session.add(match)
    session.commit()
    session.refresh(match)
    return match


def _first_event_in_round(sequence, global_round: int) -> int:
    for row in sequence:
        if row.global_round == global_round:
            return row.event_id
    raise AssertionError(f"no matches in global_round {global_round}")


def test_a_larger_draw_does_not_override_friday_saved_order(session: Session):
    tournament = _tournament(session)
    version = _version(session, tournament.id)
    womens_a = _event(session, tournament.id, "Women's A", category=EventCategory.womens, team_count=16)
    mixed_b = _event(session, tournament.id, "Mixed B", category=EventCategory.mixed, team_count=32)
    tournament.event_schedule_day_orders_json = json.dumps({"day_orders": [[womens_a.id, mixed_b.id]]})
    session.add(tournament)
    session.commit()

    _wf_match(session, tournament_id=tournament.id, event_id=womens_a.id, version_id=version.id, round_index=1, seq=1)
    _wf_match(session, tournament_id=tournament.id, event_id=mixed_b.id, version_id=version.id, round_index=1, seq=1)

    sequence = build_master_sequence(session, version.id)
    friday_r1 = [row for row in sequence if row.global_round == 0]
    assert [row.event_id for row in friday_r1] == [womens_a.id, mixed_b.id]


def test_b_lower_event_id_does_not_override_saved_order(session: Session):
    tournament = _tournament(session)
    version = _version(session, tournament.id)
    mixed_b = _event(session, tournament.id, "Mixed B", category=EventCategory.mixed, team_count=16)
    womens_a = _event(session, tournament.id, "Women's A", category=EventCategory.womens, team_count=16)
    assert mixed_b.id < womens_a.id
    tournament.event_schedule_day_orders_json = json.dumps({"day_orders": [[womens_a.id, mixed_b.id]]})
    session.add(tournament)
    session.commit()

    _wf_match(session, tournament_id=tournament.id, event_id=womens_a.id, version_id=version.id, round_index=1, seq=1)
    _wf_match(session, tournament_id=tournament.id, event_id=mixed_b.id, version_id=version.id, round_index=1, seq=1)

    sequence = build_master_sequence(session, version.id)
    assert _first_event_in_round(sequence, 0) == womens_a.id


def test_c_preserves_team_round_progression(session: Session):
    tournament = _tournament(session)
    version = _version(session, tournament.id)
    womens_a = _event(session, tournament.id, "Women's A", category=EventCategory.womens, team_count=16)
    mixed_b = _event(session, tournament.id, "Mixed B", category=EventCategory.mixed, team_count=32)
    tournament.event_schedule_day_orders_json = json.dumps({"day_orders": [[womens_a.id, mixed_b.id]]})
    session.add(tournament)
    session.commit()

    for event in (womens_a, mixed_b):
        _wf_match(session, tournament_id=tournament.id, event_id=event.id, version_id=version.id, round_index=1, seq=1)
        _wf_match(session, tournament_id=tournament.id, event_id=event.id, version_id=version.id, round_index=2, seq=1)

    sequence = build_master_sequence(session, version.id)
    assert [row.round_label for row in sequence] == [
        "WF R1",
        "WF R1",
        "WF R2",
        "WF R2",
    ]
    assert [row.event_id for row in sequence if row.match_type == "WF" and row.round_index == 1] == [
        womens_a.id,
        mixed_b.id,
    ]
    last_r1 = max(i for i, row in enumerate(sequence) if row.round_index == 1)
    first_r2 = min(i for i, row in enumerate(sequence) if row.round_index == 2)
    assert last_r1 < first_r2
    assert sequence[first_r2].event_id == womens_a.id


def test_d_saturday_order_does_not_change_friday(session: Session):
    tournament = _tournament(session)
    version = _version(session, tournament.id)
    womens_a = _event(session, tournament.id, "Women's A", category=EventCategory.womens, team_count=16)
    mixed_b = _event(session, tournament.id, "Mixed B", category=EventCategory.mixed, team_count=32)
    tournament.event_schedule_day_orders_json = json.dumps(
        {"day_orders": [[womens_a.id, mixed_b.id], [mixed_b.id, womens_a.id]]}
    )
    session.add(tournament)
    session.commit()

    for event in (womens_a, mixed_b):
        _wf_match(session, tournament_id=tournament.id, event_id=event.id, version_id=version.id, round_index=1, seq=1)
        _wf_match(session, tournament_id=tournament.id, event_id=event.id, version_id=version.id, round_index=2, seq=1)
        _main_match(
            session, tournament_id=tournament.id, event_id=event.id, version_id=version.id, round_index=1, seq=1
        )
        _main_match(
            session, tournament_id=tournament.id, event_id=event.id, version_id=version.id, round_index=2, seq=1
        )

    sequence = build_master_sequence(session, version.id)
    friday_r1 = [row.event_id for row in sequence if row.global_round == 0]
    saturday_main = [row.event_id for row in sequence if row.global_round == 2]
    assert friday_r1 == [womens_a.id, mixed_b.id]
    assert saturday_main == [mixed_b.id, womens_a.id]


def test_e_missing_saved_event_is_appended_not_dropped(session: Session):
    tournament = _tournament(session)
    version = _version(session, tournament.id)
    womens_a = _event(session, tournament.id, "Women's A", category=EventCategory.womens, team_count=8)
    mixed_b = _event(session, tournament.id, "Mixed B", category=EventCategory.mixed, team_count=32)
    tournament.event_schedule_day_orders_json = json.dumps({"day_orders": [[womens_a.id]]})
    session.add(tournament)
    session.commit()

    _wf_match(session, tournament_id=tournament.id, event_id=womens_a.id, version_id=version.id, round_index=1, seq=1)
    _wf_match(session, tournament_id=tournament.id, event_id=mixed_b.id, version_id=version.id, round_index=1, seq=1)

    sequence = build_master_sequence(session, version.id)
    friday_r1 = [row.event_id for row in sequence if row.global_round == 0]
    assert friday_r1 == [womens_a.id, mixed_b.id]


def test_f_stripped_schedule_order_still_honors_day_orders(session: Session):
    tournament = _tournament(session)
    version = _version(session, tournament.id)
    mixed_b = _event(
        session,
        tournament.id,
        "Mixed B",
        category=EventCategory.mixed,
        team_count=32,
        schedule_order=1,
    )
    womens_a = _event(
        session,
        tournament.id,
        "Women's A",
        category=EventCategory.womens,
        team_count=16,
        schedule_order=2,
    )
    mixed_b.schedule_profile_json = "{}"
    womens_a.schedule_profile_json = "{}"
    tournament.event_schedule_day_orders_json = json.dumps({"day_orders": [[womens_a.id, mixed_b.id]]})
    session.add_all([mixed_b, womens_a, tournament])
    session.commit()

    _wf_match(session, tournament_id=tournament.id, event_id=womens_a.id, version_id=version.id, round_index=1, seq=1)
    _wf_match(session, tournament_id=tournament.id, event_id=mixed_b.id, version_id=version.id, round_index=1, seq=1)

    sequence = build_master_sequence(session, version.id)
    assert _first_event_in_round(sequence, 0) == womens_a.id
