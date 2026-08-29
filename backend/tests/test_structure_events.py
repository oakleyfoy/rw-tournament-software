from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.services.structure_events import event_protection_reason


def _import_tournament(client: TestClient, source_id: int = 244) -> dict:
    created = client.post("/api/rw-os/imports", json={"tournament_id": source_id})
    assert created.status_code == 201
    return created.json()


def _approve_custom_womens(client: TestClient, import_id: int, sizes: list[int]) -> dict:
    custom = client.post(
        f"/api/rw-os/imports/{import_id}/custom-structure",
        json={"draw_kind": "womens", "sizes": sizes},
    )
    assert custom.status_code == 200
    option_key = "-".join(str(size) for size in sizes)
    approved = client.post(
        f"/api/rw-os/imports/{import_id}/approve",
        json={"selections": {"womens": option_key}},
    )
    assert approved.status_code == 200
    return approved.json()


def _expected_brackets(body: dict, draw_kind: str) -> list[dict]:
    plan = next(item for item in body["approvedPlans"] if item["drawKind"] == draw_kind)
    return plan["brackets"]


def test_a_approve_creates_events_when_none_exist(client: TestClient, session: Session):
    created = _import_tournament(client)
    import_id = created["import"]["id"]
    tournament_id = created["import"]["tournamentId"]
    assert session.exec(select(Event).where(Event.tournament_id == tournament_id)).all() == []

    approved = _approve_custom_womens(client, import_id, [20, 24])
    brackets = _expected_brackets(approved, "womens")
    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()

    assert approved["eventsCreated"] == len(brackets)
    assert len(events) == len(brackets)
    assert {event.name for event in events} == {bracket["label"] for bracket in brackets}


def test_b_derived_fields_match_approved_structure(client: TestClient, session: Session):
    created = _import_tournament(client, 148)
    import_id = created["import"]["id"]
    tournament_id = created["import"]["tournamentId"]
    womens = next(draw for draw in created["planner"]["draws"] if draw["drawKind"] == "womens")
    mixed = next(draw for draw in created["planner"]["draws"] if draw["drawKind"] == "mixed")
    womens_key = next(option for option in womens["options"] if option["recommended"])["optionKey"]
    mixed_key = mixed["options"][0]["optionKey"]

    approved = client.post(
        f"/api/rw-os/imports/{import_id}/approve",
        json={"selections": {"womens": womens_key, "mixed": mixed_key}},
    )
    assert approved.status_code == 200

    events = {
        (str(event.category.value if hasattr(event.category, "value") else event.category), event.name): event
        for event in session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
    }
    for plan in approved.json()["approvedPlans"]:
        category = "womens" if plan["drawKind"] == "womens" else "mixed"
        for bracket in plan["brackets"]:
            event = events[(category, bracket["label"])]
            assert event.team_count == bracket["size"]
            assert event.notes and "Approved structure:" in event.notes
            assert str(bracket["rankStart"]) in event.notes
            assert str(bracket["rankEnd"]) in event.notes


def test_c_approve_twice_does_not_duplicate(client: TestClient, session: Session):
    created = _import_tournament(client)
    import_id = created["import"]["id"]
    tournament_id = created["import"]["tournamentId"]
    first = _approve_custom_womens(client, import_id, [20, 24])
    first_ids = {event.id for event in session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()}

    second = client.post(
        f"/api/rw-os/imports/{import_id}/approve",
        json={"selections": {"womens": "20-24"}},
    )
    assert second.status_code == 200
    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()

    assert second.json()["eventsCreated"] == 0
    assert len(events) == first["eventsCreated"]
    assert {event.id for event in events} == first_ids
    assert {event.name for event in events} == {bracket["label"] for bracket in _expected_brackets(first, "womens")}


def test_d_matching_generated_event_is_updated(client: TestClient, session: Session):
    created = _import_tournament(client)
    import_id = created["import"]["id"]
    tournament_id = created["import"]["tournamentId"]
    existing = client.post(
        f"/api/tournaments/{tournament_id}/events",
        json={"category": "womens", "name": "Women's A", "team_count": 8, "notes": "Approved structure: placeholder"},
    )
    assert existing.status_code == 201
    existing_id = existing.json()["id"]

    approved = _approve_custom_womens(client, import_id, [20, 24])
    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
    updated = next(event for event in events if event.name == "Women's A")

    assert approved["eventsUpdated"] == 1
    assert updated.id == existing_id
    assert updated.team_count == 20
    assert updated.notes and "20 teams" in updated.notes
    assert len(events) == 2


def test_e_unrelated_manual_event_is_preserved(client: TestClient, session: Session):
    created = _import_tournament(client)
    import_id = created["import"]["id"]
    tournament_id = created["import"]["tournamentId"]
    manual = client.post(
        f"/api/tournaments/{tournament_id}/events",
        json={"category": "mixed", "name": "Open Social", "team_count": 6, "notes": "Staff added"},
    )
    assert manual.status_code == 201
    manual_id = manual.json()["id"]

    approved = _approve_custom_womens(client, import_id, [20, 24])
    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
    preserved = session.get(Event, manual_id)

    assert preserved is not None
    assert preserved.name == "Open Social"
    assert preserved.team_count == 6
    assert preserved.notes == "Staff added"
    assert approved["eventsCreated"] == 2
    assert {event.name for event in events} == {"Women's A", "Women's B", "Open Social"}


def test_f_other_tournament_events_are_never_updated(client: TestClient, session: Session):
    created = _import_tournament(client)
    import_id = created["import"]["id"]
    other = client.post(
        "/api/tournaments",
        json={
            "name": "Other Tournament",
            "location": "Elsewhere",
            "timezone": "America/New_York",
            "start_date": "2026-08-01",
            "end_date": "2026-08-02",
        },
    )
    assert other.status_code == 201
    foreign = client.post(
        f"/api/tournaments/{other.json()['id']}/events",
        json={"category": "womens", "name": "Women's A", "team_count": 99, "notes": "Leave me alone"},
    )
    assert foreign.status_code == 201
    foreign_id = foreign.json()["id"]

    _approve_custom_womens(client, import_id, [20, 24])
    untouched = session.get(Event, foreign_id)

    assert untouched is not None
    assert untouched.tournament_id == other.json()["id"]
    assert untouched.team_count == 99
    assert untouched.notes == "Leave me alone"
    assert untouched.name == "Women's A"


def test_g_incompatible_change_does_not_mutate_event_with_matches(client: TestClient, session: Session):
    created = _import_tournament(client)
    import_id = created["import"]["id"]
    tournament_id = created["import"]["tournamentId"]
    existing = client.post(
        f"/api/tournaments/{tournament_id}/events",
        json={"category": "womens", "name": "Women's A", "team_count": 8, "notes": "Locked draw"},
    )
    assert existing.status_code == 201
    event_id = existing.json()["id"]
    client.put(
        f"/api/events/{event_id}",
        json={"draw_plan_json": '{"locked": true}', "draw_status": "final"},
    )

    version = ScheduleVersion(tournament_id=tournament_id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)
    session.add(
        Match(
            tournament_id=tournament_id,
            event_id=event_id,
            schedule_version_id=version.id,
            match_code="MAIN_01",
            match_type="MAIN",
            round_number=1,
            round_index=1,
            sequence_in_round=1,
            duration_minutes=90,
            placeholder_side_a="TBD",
            placeholder_side_b="TBD",
        )
    )
    session.commit()

    approved = _approve_custom_womens(client, import_id, [20, 24])
    locked = session.get(Event, event_id)
    events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
    matches = session.exec(select(Match).where(Match.event_id == event_id)).all()

    assert locked is not None
    assert locked.team_count == 8
    assert locked.name == "Women's A"
    assert locked.draw_status == "final"
    assert locked.notes == "Locked draw"
    assert len(matches) == 1
    assert approved["structureEventConflicts"]
    assert approved["structureEventConflicts"][0]["eventId"] == event_id
    assert approved["structureEventConflicts"][0]["requestedTeamCount"] == 20
    assert {event.name for event in events} == {"Women's A", "Women's B"}
    assert next(event for event in events if event.name == "Women's B").team_count == 24
    assert approved["structureEventConflicts"][0]["reason"] == "event has generated draw"


def _add_match(
    session: Session,
    tournament_id: int,
    event_id: int,
    *,
    team_a_id: int | None = None,
    status: str = "unscheduled",
    match_code: str = "MAIN_01",
) -> Match:
    version = ScheduleVersion(tournament_id=tournament_id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)
    match = Match(
        tournament_id=tournament_id,
        event_id=event_id,
        schedule_version_id=version.id,
        match_code=match_code,
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=90,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
        team_a_id=team_a_id,
        status=status,
    )
    session.add(match)
    session.commit()
    session.refresh(match)
    return match


def test_clean_reapprove_updates_womens_ab_team_counts(client: TestClient, session: Session):
    created = _import_tournament(client)
    import_id = created["import"]["id"]
    tournament_id = created["import"]["tournamentId"]
    first = _approve_custom_womens(client, import_id, [20, 24])
    assert first["projectionOk"] is True
    assert session.exec(select(Match).where(Match.tournament_id == tournament_id)).all() == []
    events = {event.name: event for event in session.exec(select(Event).where(Event.tournament_id == tournament_id))}
    assert events["Women's A"].team_count == 20
    assert events["Women's B"].team_count == 24

    second = _approve_custom_womens(client, import_id, [24, 20])
    session.expire_all()
    events = {event.name: event for event in session.exec(select(Event).where(Event.tournament_id == tournament_id))}
    assert second["structureEventConflicts"] == []
    assert events["Women's A"].team_count == 24
    assert events["Women's B"].team_count == 20
    assert session.exec(select(Match).where(Match.tournament_id == tournament_id)).all() == []


def test_protection_is_scoped_per_event_and_tournament(client: TestClient, session: Session):
    created = _import_tournament(client)
    tournament_id = created["import"]["tournamentId"]
    first = _approve_custom_womens(client, created["import"]["id"], [20, 24])
    assert first["matchesCreated"] == 0
    event_a = session.exec(select(Event).where(Event.tournament_id == tournament_id, Event.name == "Women's A")).first()
    event_b = session.exec(select(Event).where(Event.tournament_id == tournament_id, Event.name == "Women's B")).first()
    _add_match(session, tournament_id, event_a.id, team_a_id=None, status="scheduled")

    other = client.post(
        "/api/tournaments",
        json={
            "name": "Other Tournament",
            "location": "Elsewhere",
            "timezone": "America/New_York",
            "start_date": "2026-08-01",
            "end_date": "2026-08-02",
        },
    )
    other_id = other.json()["id"]
    foreign_event = client.post(
        f"/api/tournaments/{other_id}/events",
        json={"category": "womens", "name": "Women's A", "team_count": 8},
    )
    _add_match(session, other_id, foreign_event.json()["id"], status="scheduled", match_code="FOREIGN_01")
    leaked = Match(
        tournament_id=other_id,
        event_id=event_b.id,
        schedule_version_id=session.exec(select(ScheduleVersion).where(ScheduleVersion.tournament_id == other_id))
        .first()
        .id,
        match_code="LEAK_01",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=90,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
        status="scheduled",
    )
    session.add(leaked)
    session.commit()
    session.refresh(event_a)
    session.refresh(event_b)

    assert event_protection_reason(session, event_a) == "event already has matches"
    assert event_protection_reason(session, event_b) is None


def test_placeholder_only_match_does_not_protect_clean_event(client: TestClient, session: Session):
    created = _import_tournament(client)
    import_id = created["import"]["id"]
    tournament_id = created["import"]["tournamentId"]
    _approve_custom_womens(client, import_id, [20, 24])
    event_a = session.exec(select(Event).where(Event.tournament_id == tournament_id, Event.name == "Women's A")).first()
    _add_match(session, tournament_id, event_a.id)
    session.refresh(event_a)
    assert event_a.draw_status == "not_started"
    assert not (event_a.draw_plan_json or "").strip()
    assert event_protection_reason(session, event_a) is None

    approved = _approve_custom_womens(client, import_id, [24, 20])
    session.expire_all()
    event_a = session.exec(select(Event).where(Event.tournament_id == tournament_id, Event.name == "Women's A")).first()
    assert approved["structureEventConflicts"] == []
    assert event_a.team_count == 24
