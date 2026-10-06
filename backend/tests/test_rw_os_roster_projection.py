import json
from datetime import date, datetime, time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.team_avoid_edge import TeamAvoidEdge
from app.models.temporary_player_lookup import TemporaryPlayerLookup
from app.models.tournament import Tournament
from app.models.tournament_import import TournamentDrawPlan, TournamentImport
from app.services.canonical_teams import SnapshotPlayer, SnapshotTeam, sort_teams_for_planning
from app.services.rw_os_import import persist_snapshot
from app.services.rw_os_roster_projection import (
    CONFLICT_DRAW_PROTECTION,
    CONFLICT_STRUCTURAL_SNAPSHOT,
    CONFLICT_TEAM_WOULD_MOVE,
    RWOS_LOOKUP_SOURCE,
    project_approved_roster,
)
from app.services.structure_events import event_protection_reason


def _player(
    rw_id: str,
    name: str,
    rating: float | None,
    *,
    cellphone: str | None = None,
    email: str | None = None,
    towel: str | None = None,
    identity: str = "rw_id",
) -> SnapshotPlayer:
    return SnapshotPlayer(
        rw_id=rw_id,
        name=name,
        rating=rating,
        cellphone=cellphone,
        email=email,
        towel_color=towel,
        identity_status=identity,
    )


def _team(
    key: str,
    rating: float,
    draw: str = "womens",
    *,
    cellphone1: str | None = "5551110001",
    email1: str | None = "p1@example.com",
    cellphone2: str | None = "5551110002",
    email2: str | None = "p2@example.com",
    towel1: str | None = "Blue",
    towel2: str | None = "Red",
    avoid: str | None = None,
    display: str | None = None,
    full: str | None = None,
    level: float | None = None,
) -> SnapshotTeam:
    p1, p2 = key.split("/")
    half = rating / 2
    label = "Women's" if draw == "womens" else "Mixed"
    return SnapshotTeam(
        team_key=key,
        draw_kind=draw,
        draw_label=label,
        player1=_player(p1, f"P{p1} One", half, cellphone=cellphone1, email=email1, towel=towel1),
        player2=_player(p2, f"P{p2} Two", half, cellphone=cellphone2, email=email2, towel=towel2),
        team_rating=rating,
        rating_status="complete",
        status="Confirmed",
        bucket="active",
        avoid_group=avoid,
        display_name=display,
        full_name=full,
        level=level if level is not None else rating,
    )


def _payload(source_id: int, teams: list[SnapshotTeam], *, version: str = "1") -> dict:
    return {
        "tournamentId": source_id,
        "eventName": f"RW-OS {source_id}",
        "eventDate": "2026-08-23",
        "venue": "Test",
        "updatedAt": "2026-08-23T12:00:00Z",
        "version": version,
        "teams": [team.to_dict() for team in teams],
        "waitlistTeams": [],
    }


def _womens_field(count: int, start_id: int = 100, start_rating: float = 9.0) -> list[SnapshotTeam]:
    teams = []
    for index in range(count):
        left = start_id + index * 2
        right = left + 1
        teams.append(
            _team(
                f"{left}/{right}",
                round(start_rating - index * 0.05, 4),
                avoid="A,B" if index < 3 else ("A" if index < 5 else None),
                display=f"W{index + 1}",
                full=f"Women Team {index + 1}",
            )
        )
    return teams


def _mixed_field(count: int, start_id: int = 500, start_rating: float = 8.5) -> list[SnapshotTeam]:
    teams = []
    for index in range(count):
        left = start_id + index * 2
        right = left + 1
        teams.append(
            _team(
                f"{left}/{right}",
                round(start_rating - index * 0.05, 4),
                draw="mixed",
                display=f"M{index + 1}",
                full=f"Mixed Team {index + 1}",
            )
        )
    return teams


def _import_payload(session: Session, source_id: int, teams: list[SnapshotTeam]) -> TournamentImport:
    return persist_snapshot(session, _payload(source_id, teams))


def _approve(client: TestClient, import_id: int, selections: dict[str, str]) -> dict:
    for draw_kind, option_key in selections.items():
        sizes = [int(part) for part in option_key.split("-")]
        custom = client.post(
            f"/api/rw-os/imports/{import_id}/custom-structure",
            json={"draw_kind": draw_kind, "sizes": sizes},
        )
        assert custom.status_code == 200, custom.text
    approved = client.post(f"/api/rw-os/imports/{import_id}/approve", json={"selections": selections})
    assert approved.status_code == 200, approved.text
    return approved.json()


def _teams_by_key(session: Session, tournament_id: int) -> dict[str, Team]:
    rows = session.exec(select(Team).join(Event).where(Event.tournament_id == tournament_id)).all()
    return {team.source_team_key: team for team in rows if team.source_team_key}


def test_01_migration_allows_multiple_null_source_team_keys(session: Session):
    tournament = Tournament(
        name="Manual",
        location="KC",
        timezone="America/Chicago",
        start_date=date(2026, 8, 23),
        end_date=date(2026, 8, 23),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    event = Event(tournament_id=tournament.id, category="womens", name="Women's A", team_count=3)
    session.add(event)
    session.commit()
    session.refresh(event)
    session.add(Team(event_id=event.id, name="Manual One", source_team_key=None))
    session.add(Team(event_id=event.id, name="Manual Two", source_team_key=None))
    session.add(Team(event_id=event.id, name="Manual Three", source_team_key=None))
    session.commit()
    assert len(session.exec(select(Team).where(Team.event_id == event.id)).all()) == 3


def test_02_and_03_source_team_key_unique_per_event(session: Session):
    tournament = Tournament(
        name="Keys",
        location="KC",
        timezone="America/Chicago",
        start_date=date(2026, 8, 23),
        end_date=date(2026, 8, 23),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    event = Event(tournament_id=tournament.id, category="womens", name="Women's A", team_count=2)
    session.add(event)
    session.commit()
    session.refresh(event)
    session.add(Team(event_id=event.id, name="RW One", source_team_key="1/2"))
    session.add(Team(event_id=event.id, name="RW Two", source_team_key="3/4"))
    session.commit()
    session.add(Team(event_id=event.id, name="RW Dup", source_team_key="1/2"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_04_first_projection_creates_teams(client: TestClient, session: Session):
    imported = _import_payload(session, 901, _womens_field(8))
    body = _approve(client, imported.id, {"womens": "8"})
    projection = body["rosterProjection"]
    assert projection["ok"] is True
    assert projection["created"]["teams"] == 8
    teams = _teams_by_key(session, imported.tournament_id)
    assert len(teams) == 8
    first = next(iter(teams.values()))
    assert first.source_team_key
    assert first.player1_cellphone
    assert first.p1_cell == first.player1_cellphone


def test_05_reprojection_creates_no_duplicate_team(client: TestClient, session: Session):
    imported = _import_payload(session, 902, _womens_field(8))
    first = _approve(client, imported.id, {"womens": "8"})
    second = _approve(client, imported.id, {"womens": "8"})
    assert first["rosterProjection"]["created"]["teams"] == 8
    assert second["rosterProjection"]["created"]["teams"] == 0
    assert second["rosterProjection"]["updated"]["teams"] == 8
    assert len(_teams_by_key(session, imported.tournament_id)) == 8


def test_06_planner_rank_routes_womens_abc_and_mixed_ab(client: TestClient, session: Session):
    womens = _womens_field(24)
    mixed = _mixed_field(16)
    imported = _import_payload(session, 903, womens + mixed)
    body = _approve(client, imported.id, {"womens": "8-8-8", "mixed": "8-8"})
    assert body["projectionOk"] is True

    events = {
        event.name: event
        for event in session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).all()
    }
    assert set(events) == {"Women's A", "Women's B", "Women's C", "Mixed A", "Mixed B"}

    ordered_womens = sort_teams_for_planning(womens)
    ordered_mixed = sort_teams_for_planning(mixed)
    live = _teams_by_key(session, imported.tournament_id)

    for rank, team in enumerate(ordered_womens, start=1):
        expected = "Women's A" if rank <= 8 else "Women's B" if rank <= 16 else "Women's C"
        assert session.get(Event, live[team.team_key].event_id).name == expected
    for rank, team in enumerate(ordered_mixed, start=1):
        expected = "Mixed A" if rank <= 8 else "Mixed B"
        assert session.get(Event, live[team.team_key].event_id).name == expected


def test_07_contact_fields_populate_both_representations(client: TestClient, session: Session):
    team = _team(
        "11/12",
        8.5,
        cellphone1="9045551111",
        email1="one@x.com",
        cellphone2="9045552222",
        email2="two@x.com",
        display="One / Two",
        full="One Last / Two Last",
    )
    imported = _import_payload(session, 904, [team, *_womens_field(7, start_id=200)])
    _approve(client, imported.id, {"womens": "8"})
    live = _teams_by_key(session, imported.tournament_id)["11/12"]
    assert live.player1_cellphone == "9045551111"
    assert live.p1_cell == "9045551111"
    assert live.player1_email == "one@x.com"
    assert live.p1_email == "one@x.com"
    assert live.player2_cellphone == "9045552222"
    assert live.p2_cell == "9045552222"
    assert live.player2_email == "two@x.com"
    assert live.p2_email == "two@x.com"


def test_08_and_09_contact_only_refresh_updates_contacts_not_events(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 905, teams)
    _approve(client, imported.id, {"womens": "8"})
    before = _teams_by_key(session, imported.tournament_id)
    event_ids = {team.event_id for team in before.values()}

    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in teams]
    refreshed[0].player1.cellphone = "9990001111"
    refreshed[0].player1.email = "new@x.com"
    persist_snapshot(
        session, _payload(905, refreshed, version="1"), existing=session.get(TournamentImport, imported.id)
    )

    after = _teams_by_key(session, imported.tournament_id)
    assert after[refreshed[0].team_key].player1_cellphone == "9990001111"
    assert after[refreshed[0].team_key].p1_cell == "9990001111"
    assert after[refreshed[0].team_key].p1_email == "new@x.com"
    assert {team.event_id for team in after.values()} == event_ids
    row = session.get(TournamentImport, imported.id)
    assert row.plan_status == "approved"


def test_10_wkw_sets_avoid_group(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 906, teams)
    _approve(client, imported.id, {"womens": "8"})
    live = _teams_by_key(session, imported.tournament_id)
    assert live[teams[0].team_key].avoid_group == "A,B"
    assert live[teams[3].team_key].avoid_group == "A"


def test_11_and_12_wkw_add_only_edges_and_no_duplicate(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 907, teams)
    first = _approve(client, imported.id, {"womens": "8"})
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    edges_after_first = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id)).all()
    assert first["rosterProjection"]["created"]["wkwEdges"] >= 1
    assert len(edges_after_first) == first["rosterProjection"]["created"]["wkwEdges"]
    group_a = [
        team
        for team in _teams_by_key(session, imported.tournament_id).values()
        if team.avoid_group and "A" in team.avoid_group
    ]
    assert len(group_a) >= 2

    second = _approve(client, imported.id, {"womens": "8"})
    edges_after_second = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id)).all()
    assert second["rosterProjection"]["created"]["wkwEdges"] == 0
    assert len(edges_after_second) == len(edges_after_first)


def test_13_wkw_refresh_updates_group_edges_and_keeps_manual_edges(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 908, teams)
    _approve(client, imported.id, {"womens": "8"})
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    live = _teams_by_key(session, imported.tournament_id)
    first_id = live[teams[0].team_key].id
    second_id = live[teams[1].team_key].id
    quiet_id = live[teams[7].team_key].id
    a_id, b_id = min(first_id, second_id), max(first_id, second_id)
    manual_a, manual_b = min(first_id, quiet_id), max(first_id, quiet_id)
    manual = TeamAvoidEdge(event_id=event.id, team_id_a=manual_a, team_id_b=manual_b, reason="staff note")
    session.add(manual)
    session.commit()
    session.refresh(manual)

    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in teams]
    refreshed[0].avoid_group = "B"
    persist_snapshot(
        session, _payload(908, refreshed, version="1"), existing=session.get(TournamentImport, imported.id)
    )
    session.expire_all()
    edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id)).all()
    pair_reasons = {edge.reason for edge in edges if {edge.team_id_a, edge.team_id_b} == {a_id, b_id}}
    assert "group:A" not in pair_reasons
    assert "group:B" in pair_reasons
    assert all(edge.reason != "group:A" or first_id not in {edge.team_id_a, edge.team_id_b} for edge in edges)
    kept = next(edge for edge in edges if edge.id == manual.id)
    assert kept.reason == "staff note"


def test_14_and_15_towel_rows_created_and_reprojected(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 909, teams)
    first = _approve(client, imported.id, {"womens": "8"})
    assert first["rosterProjection"]["created"]["towelRows"] == 16
    rows = session.exec(
        select(TemporaryPlayerLookup).where(TemporaryPlayerLookup.tournament_id == imported.tournament_id)
    ).all()
    assert len(rows) == 16
    assert all(row.source == RWOS_LOOKUP_SOURCE for row in rows)
    assert {row.lineup_slot for row in rows} == {1, 2}
    assert all(row.source_team_key for row in rows)

    second = _approve(client, imported.id, {"womens": "8"})
    assert second["rosterProjection"]["created"]["towelRows"] == 0
    assert (
        len(
            session.exec(
                select(TemporaryPlayerLookup).where(TemporaryPlayerLookup.tournament_id == imported.tournament_id)
            ).all()
        )
        == 16
    )


def test_16_manual_null_source_towel_rows_survive(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 910, teams)
    session.add(
        TemporaryPlayerLookup(
            tournament_id=imported.tournament_id,
            source_name="Manual Player",
            normalized_name="manual player",
            towel_color="Green",
            source=None,
        )
    )
    session.commit()
    _approve(client, imported.id, {"womens": "8"})
    rows = session.exec(
        select(TemporaryPlayerLookup).where(TemporaryPlayerLookup.tournament_id == imported.tournament_id)
    ).all()
    assert any(row.source is None and row.towel_color == "Green" for row in rows)
    assert len([row for row in rows if row.source == RWOS_LOOKUP_SOURCE]) == 16


def test_17_null_incoming_towel_does_not_wipe(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 911, teams)
    _approve(client, imported.id, {"womens": "8"})
    key = teams[0].team_key
    before = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == imported.tournament_id,
            TemporaryPlayerLookup.source_team_key == key,
            TemporaryPlayerLookup.lineup_slot == 1,
        )
    ).first()
    assert before.towel_color == "Blue"

    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in teams]
    refreshed[0].player1.towel_color = None
    persist_snapshot(
        session, _payload(911, refreshed, version="1"), existing=session.get(TournamentImport, imported.id)
    )
    after = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == imported.tournament_id,
            TemporaryPlayerLookup.source_team_key == key,
            TemporaryPlayerLookup.lineup_slot == 1,
        )
    ).first()
    assert after.towel_color == "Blue"


def test_18_structural_change_after_approval_produces_conflict(client: TestClient, session: Session):
    teams = _womens_field(16)
    imported = _import_payload(session, 912, teams)
    _approve(client, imported.id, {"womens": "8-8"})
    ordered = sort_teams_for_planning(teams)
    boundary = ordered[7]
    live_before = _teams_by_key(session, imported.tournament_id)
    original_event = live_before[boundary.team_key].event_id

    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in teams]
    mover = next(team for team in refreshed if team.team_key == boundary.team_key)
    mover.team_rating = 0.1
    session.expire_all()
    existing = session.get(TournamentImport, imported.id)
    persist_snapshot(
        session,
        _payload(912, refreshed, version="2-structural"),
        existing=existing,
    )
    session.expire_all()
    row = session.get(TournamentImport, imported.id)
    assert row.plan_status == "stale"
    plans = session.exec(select(TournamentDrawPlan).where(TournamentDrawPlan.import_id == imported.id)).all()
    result = project_approved_roster(session, row, plans, allow_structural_rebuild=False)
    assert any(conflict["code"] == CONFLICT_STRUCTURAL_SNAPSHOT for conflict in result.conflicts)
    live_after = _teams_by_key(session, imported.tournament_id)
    assert live_after[boundary.team_key].event_id == original_event


def test_19_structural_change_with_generated_draw_is_blocked(client: TestClient, session: Session):
    teams = _womens_field(16)
    imported = _import_payload(session, 913, teams)
    _approve(client, imported.id, {"womens": "8-8"})
    event_a = session.exec(
        select(Event).where(Event.tournament_id == imported.tournament_id, Event.name == "Women's A")
    ).first()
    event_a.draw_plan_json = '{"template_type":"WF_8"}'
    event_a.draw_status = "generated"
    session.add(event_a)
    version = ScheduleVersion(tournament_id=imported.tournament_id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)
    session.add(
        Match(
            tournament_id=imported.tournament_id,
            event_id=event_a.id,
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

    ordered = sort_teams_for_planning(teams)
    boundary = ordered[7]
    live_before = _teams_by_key(session, imported.tournament_id)
    original_event = live_before[boundary.team_key].event_id
    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in teams]
    next(team for team in refreshed if team.team_key == boundary.team_key).team_rating = 0.1
    session.expire_all()
    persist_snapshot(
        session,
        _payload(913, refreshed, version="2-structural"),
        existing=session.get(TournamentImport, imported.id),
    )
    session.expire_all()
    row = session.get(TournamentImport, imported.id)
    row.approved_source_hash = row.source_hash
    session.add(row)
    session.commit()
    plans = session.exec(select(TournamentDrawPlan).where(TournamentDrawPlan.import_id == imported.id)).all()
    result = project_approved_roster(session, row, plans, allow_structural_rebuild=True)
    assert result.conflicts
    assert any(
        conflict["code"] in {CONFLICT_DRAW_PROTECTION, CONFLICT_TEAM_WOULD_MOVE} for conflict in result.conflicts
    )
    live_after = _teams_by_key(session, imported.tournament_id)
    assert live_after[boundary.team_key].event_id == original_event


def test_20_existing_combined_import_still_works(client: TestClient, session: Session):
    tournament = Tournament(
        name="Combined",
        location="KC",
        timezone="America/Chicago",
        start_date=date(2026, 8, 23),
        end_date=date(2026, 8, 23),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    event = Event(tournament_id=tournament.id, category="mixed", name="Mixed", team_count=0)
    session.add(event)
    session.commit()
    text = (
        "Seed\tFirst names team\tFull name city state team\tDraw\tLevel\tCell phone first player\tEmail first player\n"
        "1\tAlpha / Beta\tAlpha Last / Beta Last\tMixed\t9.0\t5550000001\ta@x.com"
    )
    resp = client.post(f"/api/tournaments/{tournament.id}/teams/import-combined", json={"text": text})
    assert resp.status_code == 200, resp.text
    team = session.exec(select(Team).where(Team.event_id == event.id)).first()
    assert team.source_team_key is None
    assert team.p1_cell == "5550000001"
    assert team.player1_cellphone == "5550000001"


def test_projection_warnings_include_missing_operational_fields(client: TestClient, session: Session):
    incomplete = _team(
        "21/22",
        8.0,
        cellphone1=None,
        email1=None,
        cellphone2=None,
        email2=None,
        towel1=None,
        towel2=None,
        avoid=None,
        display="Incomplete",
        full="Incomplete Team",
    )
    imported = _import_payload(session, 914, [incomplete, *_womens_field(7, start_id=300)])
    body = _approve(client, imported.id, {"womens": "8"})
    codes = {warning["code"] for warning in body["rosterProjection"]["warnings"]}
    assert "missing_player1_cellphone" in codes
    assert "missing_towel_color" in codes
    assert "missing_who_knows_who" in codes


def test_combined_import_does_not_wipe_rwos_towel_rows(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 920, teams)
    _approve(client, imported.id, {"womens": "8"})
    before = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == imported.tournament_id,
            TemporaryPlayerLookup.source == RWOS_LOOKUP_SOURCE,
        )
    ).all()
    assert len(before) == 16
    rwos_ids = {row.id for row in before}

    text = (
        "Seed\tFirst names team\tFull name city state team\tDraw\tLevel\t"
        "Cell phone first player\tEmail first player\ttowel color first player\n"
        "1\tAlpha / Beta\tWomen Team 1\tWomen's A\t9.0\t5550000001\ta@x.com\tYellow"
    )
    resp = client.post(f"/api/tournaments/{imported.tournament_id}/teams/import-combined", json={"text": text})
    assert resp.status_code == 200, resp.text
    session.expire_all()
    after = session.exec(
        select(TemporaryPlayerLookup).where(TemporaryPlayerLookup.tournament_id == imported.tournament_id)
    ).all()
    surviving = [row for row in after if row.source == RWOS_LOOKUP_SOURCE]
    legacy = [row for row in after if row.source is None]
    assert {row.id for row in surviving} == rwos_ids
    assert len(legacy) == 1
    assert legacy[0].towel_color == "Yellow"


def test_lookup_source_identity_constraints(session: Session):
    tournament = Tournament(
        name="Lookup keys",
        location="KC",
        timezone="America/Chicago",
        start_date=date(2026, 8, 23),
        end_date=date(2026, 8, 23),
    )
    session.add(tournament)
    session.commit()
    session.refresh(tournament)
    session.add(
        TemporaryPlayerLookup(
            tournament_id=tournament.id,
            source_name="Manual A",
            normalized_name="manual a",
            towel_color="Green",
            source=None,
        )
    )
    session.add(
        TemporaryPlayerLookup(
            tournament_id=tournament.id,
            source_name="Manual B",
            normalized_name="manual b",
            towel_color="Pink",
            source=None,
        )
    )
    session.add(
        TemporaryPlayerLookup(
            tournament_id=tournament.id,
            source_name="P1",
            normalized_name="p1",
            towel_color="Blue",
            source=RWOS_LOOKUP_SOURCE,
            source_team_key="1/2",
            lineup_slot=1,
        )
    )
    session.add(
        TemporaryPlayerLookup(
            tournament_id=tournament.id,
            source_name="P2",
            normalized_name="p2",
            towel_color="Red",
            source=RWOS_LOOKUP_SOURCE,
            source_team_key="1/2",
            lineup_slot=2,
        )
    )
    session.add(
        TemporaryPlayerLookup(
            tournament_id=tournament.id,
            source_name="Q1",
            normalized_name="q1",
            towel_color="Black",
            source=RWOS_LOOKUP_SOURCE,
            source_team_key="3/4",
            lineup_slot=1,
        )
    )
    session.commit()
    session.add(
        TemporaryPlayerLookup(
            tournament_id=tournament.id,
            source_name="Dup",
            normalized_name="dup",
            towel_color="White",
            source=RWOS_LOOKUP_SOURCE,
            source_team_key="1/2",
            lineup_slot=1,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_stale_is_recoverable_through_explicit_reapproval(client: TestClient, session: Session):
    teams = _womens_field(16)
    imported = _import_payload(session, 921, teams)
    first = _approve(client, imported.id, {"womens": "8-8"})
    session.expire_all()
    row = session.get(TournamentImport, imported.id)
    original_approved_hash = row.approved_source_hash
    assert original_approved_hash == row.source_hash
    ordered = sort_teams_for_planning(teams)
    boundary = ordered[7]
    original_event = _teams_by_key(session, imported.tournament_id)[boundary.team_key].event_id

    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in teams]
    next(team for team in refreshed if team.team_key == boundary.team_key).team_rating = 0.1
    persist_snapshot(
        session,
        _payload(921, refreshed, version="structural-refresh"),
        existing=session.get(TournamentImport, imported.id),
    )
    session.expire_all()
    stale = session.get(TournamentImport, imported.id)
    assert stale.plan_status == "stale"
    assert stale.approved_source_hash != stale.source_hash
    blocked = project_approved_roster(
        session,
        stale,
        session.exec(select(TournamentDrawPlan).where(TournamentDrawPlan.import_id == imported.id)).all(),
        allow_structural_rebuild=False,
    )
    assert any(conflict["code"] == CONFLICT_STRUCTURAL_SNAPSHOT for conflict in blocked.conflicts)
    assert _teams_by_key(session, imported.tournament_id)[boundary.team_key].event_id == original_event

    second = _approve(client, imported.id, {"womens": "8-8"})
    session.expire_all()
    recovered = session.get(TournamentImport, imported.id)
    assert recovered.plan_status == "approved"
    assert recovered.approved_source_hash == recovered.source_hash
    assert recovered.approved_source_hash != original_approved_hash
    assert second["projectionOk"] is True
    moved = _teams_by_key(session, imported.tournament_id)[boundary.team_key]
    assert moved.event_id != original_event
    assert first["rosterProjection"]["created"]["teams"] == 16


def test_operational_refresh_does_not_change_event_membership(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 922, teams)
    _approve(client, imported.id, {"womens": "8"})
    before = _teams_by_key(session, imported.tournament_id)
    event_ids = {team.source_team_key: team.event_id for team in before.values()}
    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in teams]
    refreshed[0].player1.cellphone = "1112223333"
    refreshed[0].player1.email = "ops@example.com"
    refreshed[0].player1.towel_color = "Lime"
    refreshed[0].avoid_group = "B"
    refreshed[0].display_name = "Ops / Refresh"
    refreshed[0].full_name = "Ops Refresh"
    refreshed[0].level = 9.9
    persist_snapshot(
        session, _payload(922, refreshed, version="1"), existing=session.get(TournamentImport, imported.id)
    )
    session.expire_all()
    row = session.get(TournamentImport, imported.id)
    assert row.plan_status == "approved"
    after = _teams_by_key(session, imported.tournament_id)
    assert {team.source_team_key: team.event_id for team in after.values()} == event_ids
    updated = after[refreshed[0].team_key]
    assert updated.player1_cellphone == "1112223333"
    assert updated.p1_email == "ops@example.com"
    assert updated.avoid_group == "B"
    assert updated.display_name == "Ops / Refresh"
    assert updated.name == "Ops Refresh"
    assert updated.rating == 9.9
    towel = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == imported.tournament_id,
            TemporaryPlayerLookup.source_team_key == refreshed[0].team_key,
            TemporaryPlayerLookup.lineup_slot == 1,
        )
    ).first()
    assert towel.towel_color == "Lime"
    assert session.exec(select(Match).where(Match.tournament_id == imported.tournament_id)).all() == []


def test_draw_builder_shape_after_projection(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 923, teams)
    _approve(client, imported.id, {"womens": "8"})
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    live = session.exec(select(Team).where(Team.event_id == event.id)).all()
    assert event is not None
    assert len(live) == 8
    assert sorted(team.seed for team in live) == list(range(1, 9))
    assert all(team.name and team.display_name for team in live)
    assert all(team.rating is not None for team in live)
    assert all(team.player1_cellphone and team.p1_cell for team in live)
    assert any(team.avoid_group for team in live)
    edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id)).all()
    assert edges
    assert all((edge.reason or "").startswith("group:") for edge in edges)


def test_player_sync_always_runs_on_roster_projection(client: TestClient, session: Session):
    from app.models.player import Player

    teams = _womens_field(8)
    imported = _import_payload(session, 924, teams)
    _approve(client, imported.id, {"womens": "8"})
    players = session.exec(select(Player).where(Player.tournament_id == imported.tournament_id)).all()
    assert players


def test_protected_event_allows_operational_contact_and_towel_updates(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 925, teams)
    _approve(client, imported.id, {"womens": "8"})
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    event.draw_plan_json = '{"template_type":"WF_8"}'
    event.draw_status = "generated"
    session.add(event)
    session.commit()
    key = teams[0].team_key
    original_event_id = _teams_by_key(session, imported.tournament_id)[key].event_id
    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in teams]
    refreshed[0].player1.cellphone = "4445556666"
    refreshed[0].player1.email = "protected@example.com"
    refreshed[0].player1.towel_color = "Orange"
    refreshed[0].display_name = "Prot / Team"
    refreshed[0].full_name = "Protected Team"
    refreshed[0].level = 8.8
    persist_snapshot(
        session, _payload(925, refreshed, version="1"), existing=session.get(TournamentImport, imported.id)
    )
    session.expire_all()
    live = _teams_by_key(session, imported.tournament_id)[key]
    assert live.event_id == original_event_id
    assert live.player1_cellphone == "4445556666"
    assert live.p1_email == "protected@example.com"
    assert live.display_name == "Prot / Team"
    assert live.name == "Protected Team"
    assert live.rating == 8.8
    towel = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == imported.tournament_id,
            TemporaryPlayerLookup.source_team_key == key,
            TemporaryPlayerLookup.lineup_slot == 1,
        )
    ).first()
    assert towel.towel_color == "Orange"


def test_approve_clean_import_creates_no_matches_and_projects_roster(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 926, teams)
    body = _approve(client, imported.id, {"womens": "8"})
    assert body["projectionOk"] is True
    assert body["matchesCreated"] == 0
    assert body["rosterProjection"]["created"]["teams"] == 8
    assert body["rosterProjection"]["created"]["towelRows"] == 16
    assert session.exec(select(Match).where(Match.tournament_id == imported.tournament_id)).all() == []
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    assert event_protection_reason(session, event) is None


def test_placeholder_match_does_not_block_roster_projection(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 927, teams)
    _approve(client, imported.id, {"womens": "8"})
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    version = ScheduleVersion(tournament_id=imported.tournament_id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)
    session.add(
        Match(
            tournament_id=imported.tournament_id,
            event_id=event.id,
            schedule_version_id=version.id,
            match_code="SCAFFOLD_01",
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
    session.refresh(event)
    assert event_protection_reason(session, event) is None
    body = _approve(client, imported.id, {"womens": "8"})
    assert body["projectionOk"] is True
    assert body["structureEventConflicts"] == []
    assert len(_teams_by_key(session, imported.tournament_id)) == 8


def test_generated_draw_still_blocks_structural_projection(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 928, teams)
    _approve(client, imported.id, {"womens": "8"})
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    event.draw_plan_json = '{"template_type":"WF_8"}'
    event.draw_status = "generated"
    session.add(event)
    session.commit()
    session.refresh(event)
    assert event_protection_reason(session, event) == "event has generated draw"
    body = _approve(client, imported.id, {"womens": "8"})
    assert body["structureEventConflicts"] == []
    # Re-approve same size is allowed (no team_count change), but structural rematch stays on this Event.
    assert _teams_by_key(session, imported.tournament_id)
    assert all(team.event_id == event.id for team in _teams_by_key(session, imported.tournament_id).values())


def _approve_amelia(client: TestClient, import_id: int, *, womens: list[int], mixed: list[int]) -> dict:
    client.put(
        f"/api/rw-os/imports/{import_id}/forecasts",
        json={"forecasts": {"womens": sum(womens), "mixed": sum(mixed)}},
    )
    return _approve(
        client,
        import_id,
        {"womens": "-".join(str(size) for size in womens), "mixed": "-".join(str(size) for size in mixed)},
    )


def _event_map(session: Session, tournament_id: int) -> dict[str, Event]:
    return {event.name: event for event in session.exec(select(Event).where(Event.tournament_id == tournament_id))}


def _source_counts(session: Session, tournament_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in session.exec(select(Event).where(Event.tournament_id == tournament_id)):
        counts[event.name] = len(
            session.exec(select(Team).where(Team.event_id == event.id, Team.source_team_key.is_not(None))).all()
        )
    return counts


def test_amelia_clean_reapprove_updates_capacity_and_routes_67_womens(client: TestClient, session: Session):
    teams = _womens_field(67) + _mixed_field(44)
    imported = _import_payload(session, 1470, teams)
    first = _approve_amelia(client, imported.id, womens=[24, 20, 24], mixed=[20, 24])
    assert first["projectionOk"] is True
    assert first["structureEventConflicts"] == []
    session.expire_all()
    events = _event_map(session, imported.tournament_id)
    assert events["Women's A"].team_count == 24
    assert events["Women's B"].team_count == 20
    assert events["Women's C"].team_count == 24
    assert _source_counts(session, imported.tournament_id) == {
        "Mixed A": 20,
        "Mixed B": 24,
        "Women's A": 24,
        "Women's B": 20,
        "Women's C": 23,
    }
    assert session.exec(select(Match).where(Match.tournament_id == imported.tournament_id)).all() == []

    second = _approve_amelia(client, imported.id, womens=[20, 24, 24], mixed=[20, 24])
    session.expire_all()
    events = _event_map(session, imported.tournament_id)
    assert second["structureEventConflicts"] == []
    assert events["Mixed A"].team_count == 20
    assert events["Mixed B"].team_count == 24
    assert events["Women's A"].team_count == 20
    assert events["Women's B"].team_count == 24
    assert events["Women's C"].team_count == 24
    assert "ranks 1–20" in (events["Women's A"].notes or "")
    assert "20 teams" in (events["Women's A"].notes or "")
    assert "ranks 21–44" in (events["Women's B"].notes or "")
    assert "24 teams" in (events["Women's B"].notes or "")
    assert _source_counts(session, imported.tournament_id) == {
        "Mixed A": 20,
        "Mixed B": 24,
        "Women's A": 20,
        "Women's B": 24,
        "Women's C": 23,
    }
    assert len(_teams_by_key(session, imported.tournament_id)) == 111
    assert session.exec(select(Match).where(Match.tournament_id == imported.tournament_id)).all() == []

    reopened = client.get(f"/api/rw-os/imports/{imported.id}")
    assert reopened.status_code == 200
    body = reopened.json()
    assert body["liveRoster"]["teams"]["sourceBacked"] == 111
    assert body["rosterProjection"]["created"]["teams"] == 111
    names = {event["name"]: event for event in body["tournamentEvents"]}
    assert names["Women's A"]["teamCount"] == 20
    assert names["Women's A"]["teamRowCount"] == 20
    assert names["Women's C"]["teamCount"] == 24
    assert names["Women's C"]["teamRowCount"] == 23


def test_amelia_draft_draw_templates_do_not_block_capacity_or_roster(client: TestClient, session: Session):
    """Production shape: every Event held a saved Draw Builder template and zero teams.

    A draft template must not be read as a live draw, or approval silently keeps the old
    capacity and projects no roster at all.
    """
    teams = _womens_field(67) + _mixed_field(44)
    imported = _import_payload(session, 1472, teams)
    _approve_amelia(client, imported.id, womens=[24, 20, 24], mixed=[20, 24])
    session.expire_all()
    for event in _event_map(session, imported.tournament_id).values():
        saved = client.put(
            f"/api/events/{event.id}/draw-plan",
            json={"draw_plan_json": '{"version":"1.0","template_type":"WF_TO_POOLS_4","wf_rounds":2}'},
        )
        assert saved.status_code == 200, saved.text
    session.expire_all()
    for event in _event_map(session, imported.tournament_id).values():
        assert event.draw_status == "draft"
        assert event_protection_reason(session, event) is None

    body = _approve_amelia(client, imported.id, womens=[20, 24, 24], mixed=[20, 24])
    session.expire_all()
    events = _event_map(session, imported.tournament_id)
    assert body["structureEventConflicts"] == []
    assert body["projectionOk"] is True
    assert events["Women's A"].team_count == 20
    assert events["Women's B"].team_count == 24
    assert events["Women's C"].team_count == 24
    assert _source_counts(session, imported.tournament_id) == {
        "Mixed A": 20,
        "Mixed B": 24,
        "Women's A": 20,
        "Women's B": 24,
        "Women's C": 23,
    }
    assert all("WF_TO_POOLS_4" in (event.draw_plan_json or "") for event in events.values())
    assert session.exec(select(Match).where(Match.tournament_id == imported.tournament_id)).all() == []


def test_amelia_notes_and_capacity_stay_aligned_when_teams_already_exist(client: TestClient, session: Session):
    teams = _womens_field(67)
    imported = _import_payload(session, 1471, teams)
    client.put(f"/api/rw-os/imports/{imported.id}/forecasts", json={"forecasts": {"womens": 68}})
    _approve(client, imported.id, {"womens": "24-20-24"})
    session.expire_all()
    event_a = _event_map(session, imported.tournament_id)["Women's A"]
    event_a.notes = "Approved structure: Women's A · ranks 1–20 · 20 teams"
    session.add(event_a)
    session.commit()

    body = _approve(client, imported.id, {"womens": "20-24-24"})
    session.expire_all()
    event_a = _event_map(session, imported.tournament_id)["Women's A"]
    event_b = _event_map(session, imported.tournament_id)["Women's B"]
    assert body["structureEventConflicts"] == []
    assert event_a.team_count == 20
    assert event_b.team_count == 24
    assert "20 teams" in (event_a.notes or "")
    assert "24 teams" in (event_b.notes or "")
    assert _source_counts(session, imported.tournament_id)["Women's A"] == 20
    assert _source_counts(session, imported.tournament_id)["Women's B"] == 24


def test_operational_refresh_updates_identity_without_moving_or_creating_matches(client: TestClient, session: Session):
    womens = _womens_field(8)
    mixed = _mixed_field(8)
    imported = _import_payload(session, 930, womens + mixed)
    _approve(client, imported.id, {"womens": "8", "mixed": "8"})
    before = _teams_by_key(session, imported.tournament_id)
    original_event = before[womens[0].team_key].event_id
    mixed_event_ids = {
        team.event_id for team in before.values() if team.source_team_key in {row.team_key for row in mixed}
    }
    matches_before = session.exec(select(Match).where(Match.tournament_id == imported.tournament_id)).all()

    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in womens + mixed]
    target = next(team for team in refreshed if team.team_key == womens[0].team_key)
    target.display_name = "Short / Names"
    target.full_name = "Full Names, City, ST"
    target.level = 7.75
    target.player1.cellphone = "2223334444"
    target.player1.email = "short@example.com"
    target.player1.towel_color = "Teal"
    persisted = persist_snapshot(
        session, _payload(930, refreshed, version="1"), existing=session.get(TournamentImport, imported.id)
    )
    projection = getattr(persisted, "_last_roster_projection", None) or {}
    changes = {item["field"]: item for item in projection.get("fieldChanges") or []}
    assert changes["displayName"]["before"] == "W1"
    assert changes["displayName"]["after"] == "Short / Names"
    assert changes["fullName"]["before"] == "Women Team 1"
    assert changes["fullName"]["after"] == "Full Names, City, ST"
    assert changes["rating"]["after"] == 7.75
    assert changes["player1Cellphone"]["after"] == "2223334444"
    assert changes["player1Email"]["after"] == "short@example.com"
    assert changes["player1Towel"]["before"] == "Blue"
    assert changes["player1Towel"]["after"] == "Teal"
    session.expire_all()

    after = _teams_by_key(session, imported.tournament_id)
    updated = after[womens[0].team_key]
    assert updated.event_id == original_event
    assert updated.display_name == "Short / Names"
    assert updated.name == "Full Names, City, ST"
    assert updated.rating == 7.75
    assert updated.player1_cellphone == "2223334444"
    assert updated.p1_email == "short@example.com"
    assert {
        team.event_id for team in after.values() if team.source_team_key in {row.team_key for row in mixed}
    } == mixed_event_ids
    towel = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == imported.tournament_id,
            TemporaryPlayerLookup.source_team_key == womens[0].team_key,
            TemporaryPlayerLookup.lineup_slot == 1,
        )
    ).first()
    assert towel.towel_color == "Teal"
    matches_after = session.exec(select(Match).where(Match.tournament_id == imported.tournament_id)).all()
    assert len(matches_after) == len(matches_before) == 0


def test_operational_refresh_adds_team_when_draw_exists_but_play_has_not_started(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 931, teams)
    _approve(client, imported.id, {"womens": "8"})
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).first()
    event.draw_plan_json = '{"template_type":"WF_8"}'
    event.draw_status = "generated"
    session.add(event)
    session.commit()
    before = _teams_by_key(session, imported.tournament_id)
    original_event_ids = {key: team.event_id for key, team in before.items()}

    extra = _team("900/901", 8.0, display="New", full="New Team")
    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in teams] + [extra]
    persist_snapshot(
        session,
        _payload(931, refreshed, version="2-structural"),
        existing=session.get(TournamentImport, imported.id),
    )
    session.expire_all()
    after = _teams_by_key(session, imported.tournament_id)
    assert extra.team_key in after
    assert after[extra.team_key].is_defaulted is False
    assert after[extra.team_key].event_id == event.id
    assert {key: team.event_id for key, team in after.items() if key in original_event_ids} == original_event_ids
    assert session.exec(select(Match).where(Match.tournament_id == imported.tournament_id)).all() == []


def _torrie_nancy() -> SnapshotTeam:
    team = _team(
        "8801/8802",
        9.0,
        display="Torrie / Nancy",
        full="Torrie Example / Nancy Example",
        towel1="Purple",
        towel2="Gold",
        avoid="A",
        cellphone1="5559990001",
        email1="torrie@example.com",
        cellphone2="5559990002",
        email2="nancy@example.com",
    )
    team.player1.name = "Torrie"
    team.player2.name = "Nancy"
    return team


def _assign_unplayed_wf_slot(session: Session, tournament_id: int, event: Event, team_a: Team, team_b: Team) -> Match:
    version = ScheduleVersion(tournament_id=tournament_id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)
    match = Match(
        tournament_id=tournament_id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code="WF_R1_01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team_a.id,
        team_b_id=team_b.id,
        placeholder_side_a=team_a.name,
        placeholder_side_b=team_b.name,
    )
    session.add(match)
    event.draw_plan_json = '{"template_type":"WF_8"}'
    event.draw_status = "generated"
    session.add(event)
    session.commit()
    session.refresh(match)
    return match


def _schedule_match(session: Session, tournament: Tournament, match: Match) -> tuple[MatchAssignment, ScheduleSlot]:
    slot = ScheduleSlot(
        tournament_id=tournament.id,
        schedule_version_id=match.schedule_version_id,
        day_date=tournament.start_date,
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=3,
        court_label="Court 3",
        block_minutes=60,
    )
    session.add(slot)
    session.commit()
    session.refresh(slot)
    assignment = MatchAssignment(
        schedule_version_id=match.schedule_version_id,
        match_id=match.id,
        slot_id=slot.id,
        assigned_by="POLICY",
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment, slot


def test_refresh_replaces_withdrawn_team_with_torrie_nancy_before_play(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 940, teams)
    _approve(client, imported.id, {"womens": "8"})
    session.expire_all()
    live = _teams_by_key(session, imported.tournament_id)
    withdrawn = live[teams[0].team_key]
    partner = live[teams[1].team_key]
    event = session.get(Event, withdrawn.event_id)
    match = _assign_unplayed_wf_slot(session, imported.tournament_id, event, withdrawn, partner)
    tournament = session.get(Tournament, imported.tournament_id)
    assignment, slot = _schedule_match(session, tournament, match)
    match_id = match.id
    assignment_id = assignment.id
    slot_id = slot.id
    version_id = match.schedule_version_id
    matches_before = session.exec(select(Match).where(Match.tournament_id == imported.tournament_id)).all()
    before_edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id)).all()
    assert any(edge.team_id_a == withdrawn.id or edge.team_id_b == withdrawn.id for edge in before_edges)
    before_towels = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == imported.tournament_id,
            TemporaryPlayerLookup.source_team_key == withdrawn.source_team_key,
        )
    ).all()
    assert len(before_towels) == 2

    replacement = _torrie_nancy()
    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in teams[1:]]
    refreshed.append(replacement)
    persisted = persist_snapshot(
        session,
        _payload(940, refreshed, version="replacement"),
        existing=session.get(TournamentImport, imported.id),
    )
    projection = getattr(persisted, "_last_roster_projection", None) or {}
    assert projection["reconciled"]["withdrawnTeams"] == 1
    assert projection["reconciled"]["drawSlotsReplaced"] == 1
    assert projection["created"]["teams"] == 1
    assert not any(conflict["code"] == "roster_reconciliation_blocked" for conflict in projection["conflicts"])

    session.expire_all()
    after = _teams_by_key(session, imported.tournament_id)
    assert replacement.team_key in after
    new_team = after[replacement.team_key]
    assert new_team.is_defaulted is False
    assert new_team.event_id == event.id
    assert new_team.display_name == "Torrie / Nancy"
    assert new_team.player1_cellphone == "5559990001"
    assert new_team.player1_email == "torrie@example.com"
    assert new_team.avoid_group == "A"
    assert list(after).count(replacement.team_key) == 1

    old = session.get(Team, withdrawn.id)
    assert old.is_defaulted is True
    assert old.source_team_key == teams[0].team_key

    session.refresh(match)
    assert match.id == match_id
    assert match.team_a_id == new_team.id
    assert match.team_b_id == partner.id
    assert match.match_code == "WF_R1_01"
    assert match.round_index == 1
    assert match.sequence_in_round == 1
    assert match.schedule_version_id == version_id
    assert match.winner_team_id is None
    assert match.score_json is None
    matches_after = session.exec(select(Match).where(Match.tournament_id == imported.tournament_id)).all()
    assert {row.id for row in matches_after} == {row.id for row in matches_before}
    session.refresh(assignment)
    session.refresh(slot)
    assert assignment.id == assignment_id
    assert assignment.match_id == match.id
    assert assignment.slot_id == slot_id
    assert slot.court_number == 3
    assert slot.court_label == "Court 3"
    assert slot.day_date == tournament.start_date
    assert str(slot.start_time).startswith("09:00")

    towels = session.exec(
        select(TemporaryPlayerLookup).where(TemporaryPlayerLookup.tournament_id == imported.tournament_id)
    ).all()
    by_key = {(row.source_team_key, row.lineup_slot): row.towel_color for row in towels if row.source == "rwos-import"}
    assert by_key[(replacement.team_key, 1)] == "Purple"
    assert by_key[(replacement.team_key, 2)] == "Gold"
    assert all(row.source_team_key != withdrawn.source_team_key for row in towels)

    edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id)).all()
    assert all(edge.team_id_a != old.id and edge.team_id_b != old.id for edge in edges)
    assert any(edge.team_id_a == new_team.id or edge.team_id_b == new_team.id for edge in edges)

    active = [team for team in after.values() if not team.is_defaulted]
    assert len(active) == 8
    desk = client.get(f"/api/desk/tournaments/{imported.tournament_id}/teams")
    assert desk.status_code == 200, desk.text
    desk_ids = {row["team_id"] for row in desk.json()}
    assert new_team.id in desk_ids
    assert old.id not in desk_ids

    checkin = client.get(
        f"/api/desk/tournaments/{imported.tournament_id}/checkin/queue",
        params={"version_id": version_id},
    )
    assert checkin.status_code == 200, checkin.text
    checkin_ids = set()
    for row in checkin.json()["checkin_matches"]:
        checkin_ids.add(row["side_a"]["team_id"])
        checkin_ids.add(row["side_b"]["team_id"])
    assert new_team.id in checkin_ids
    assert old.id not in checkin_ids

    sms = client.post(
        f"/api/tournaments/{imported.tournament_id}/sms/preview/event/{event.id}",
        json={"message": "Roster check"},
    )
    assert sms.status_code == 200, sms.text
    sms_ids = {row["team_id"] for row in sms.json()["recipients"]}
    assert new_team.id in sms_ids
    assert old.id not in sms_ids

    chart = client.get(f"/api/desk/tournaments/{imported.tournament_id}/temporary-player-lookups")
    assert chart.status_code == 200, chart.text
    chart_colors = {item["towel_color"] for item in chart.json()["items"]}
    chart_names = " ".join(item["source_name"] for item in chart.json()["items"])
    assert "Purple" in chart_colors
    assert "Gold" in chart_colors
    assert "Torrie" in chart_names
    assert "Nancy" in chart_names
    assert "P100" not in chart_names

    wkw = client.get(f"/api/events/{event.id}/avoid-edges")
    assert wkw.status_code == 200, wkw.text
    wkw_ids = {edge["team_id_a"] for edge in wkw.json()} | {edge["team_id_b"] for edge in wkw.json()}
    assert new_team.id in wkw_ids
    assert old.id not in wkw_ids

    towel_ids = {
        row.id for row in towels if row.source == "rwos-import" and row.source_team_key == replacement.team_key
    }
    edge_ids = {edge.id for edge in edges if edge.team_id_a == new_team.id or edge.team_id_b == new_team.id}
    again = persist_snapshot(
        session,
        _payload(940, refreshed, version="replacement"),
        existing=session.get(TournamentImport, imported.id),
    )
    second = getattr(again, "_last_roster_projection", None) or {}
    assert second["created"]["teams"] == 0
    assert second["reconciled"]["withdrawnTeams"] == 0
    assert second["reconciled"]["drawSlotsReplaced"] == 0
    assert not any(
        conflict["code"] in {"roster_reconciliation_blocked", "roster_draw_placement_unresolved"}
        for conflict in second["conflicts"]
    )
    session.expire_all()
    replay = _teams_by_key(session, imported.tournament_id)
    assert list(replay).count(replacement.team_key) == 1
    session.refresh(match)
    assert match.team_a_id == new_team.id
    assert match.team_b_id == partner.id
    replay_towels = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == imported.tournament_id,
            TemporaryPlayerLookup.source == "rwos-import",
            TemporaryPlayerLookup.source_team_key == replacement.team_key,
        )
    ).all()
    assert {row.id for row in replay_towels} == towel_ids
    assert len(replay_towels) == 2
    replay_edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id)).all()
    assert {
        edge.id for edge in replay_edges if edge.team_id_a == new_team.id or edge.team_id_b == new_team.id
    } == edge_ids
    assert all(edge.team_id_a != old.id and edge.team_id_b != old.id for edge in replay_edges)


def test_later_refresh_places_replacement_into_slot_left_open(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 942, teams)
    _approve(client, imported.id, {"womens": "8"})
    session.expire_all()
    live = _teams_by_key(session, imported.tournament_id)
    withdrawn = live[teams[0].team_key]
    partner = live[teams[1].team_key]
    event = session.get(Event, withdrawn.event_id)
    match = _assign_unplayed_wf_slot(session, imported.tournament_id, event, withdrawn, partner)

    remaining = [SnapshotTeam.from_dict(team.to_dict()) for team in teams[1:]]
    first = persist_snapshot(
        session,
        _payload(942, remaining, version="withdrawn-only"),
        existing=session.get(TournamentImport, imported.id),
    )
    opened = getattr(first, "_last_roster_projection", None) or {}
    assert opened["reconciled"]["withdrawnTeams"] == 1
    assert opened["reconciled"]["drawSlotsReplaced"] == 0
    session.refresh(match)
    assert match.team_a_id is None
    assert match.placeholder_side_a == "TBD"
    assert match.team_b_id == partner.id

    replacement = _torrie_nancy()
    replacement.player2.towel_color = None
    second = persist_snapshot(
        session,
        _payload(942, remaining + [replacement], version="replacement-later"),
        existing=session.get(TournamentImport, imported.id),
    )
    placed = getattr(second, "_last_roster_projection", None) or {}
    assert placed["created"]["teams"] == 1
    assert placed["reconciled"]["drawSlotsReplaced"] == 1
    assert not any(item["code"] == "roster_draw_placement_unresolved" for item in placed["conflicts"])
    assert any(item["code"] == "missing_towel_color" for item in placed["warnings"])

    session.expire_all()
    new_team = _teams_by_key(session, imported.tournament_id)[replacement.team_key]
    session.refresh(match)
    assert match.team_a_id == new_team.id
    assert match.team_b_id == partner.id
    assert match.placeholder_side_a == new_team.name


def test_refresh_does_not_rewrite_started_match_and_reports_conflict(client: TestClient, session: Session):
    teams = _womens_field(8)
    imported = _import_payload(session, 941, teams)
    _approve(client, imported.id, {"womens": "8"})
    session.expire_all()
    live = _teams_by_key(session, imported.tournament_id)
    withdrawn = live[teams[0].team_key]
    partner = live[teams[1].team_key]
    event = session.get(Event, withdrawn.event_id)
    match = _assign_unplayed_wf_slot(session, imported.tournament_id, event, withdrawn, partner)
    match.started_at = datetime.utcnow()
    match.runtime_status = "FINAL"
    match.score_json = {"display": "4-2"}
    match.winner_team_id = withdrawn.id
    session.add(match)
    session.commit()
    advanced = Match(
        tournament_id=imported.tournament_id,
        event_id=event.id,
        schedule_version_id=match.schedule_version_id,
        match_code="WF_R2_01",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=withdrawn.id,
        source_match_a_id=match.id,
        source_a_role="WINNER",
        placeholder_side_a=withdrawn.name,
        placeholder_side_b="TBD",
    )
    session.add(advanced)
    session.commit()
    session.refresh(advanced)

    replacement = _torrie_nancy()
    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in teams[1:]]
    survivor = next(team for team in refreshed if team.team_key == teams[1].team_key)
    survivor.player1.cellphone = "5557778888"
    survivor.player1.email = "survivor@example.com"
    survivor.player1.towel_color = "Lime"
    refreshed.append(replacement)
    persisted = persist_snapshot(
        session,
        _payload(941, refreshed, version="protected-replacement"),
        existing=session.get(TournamentImport, imported.id),
    )
    projection = getattr(persisted, "_last_roster_projection", None) or {}
    blocked = [item for item in projection["conflicts"] if item["code"] == "roster_reconciliation_blocked"]
    assert len(blocked) == 1
    assert not any(item["code"] == "roster_draw_placement_unresolved" for item in projection["conflicts"])
    message = blocked[0]["message"]
    assert "W1" in message or teams[0].team_key in message
    assert "Torrie / Nancy" in message
    assert event.name in message
    assert projection["reconciled"]["drawSlotsReplaced"] == 0
    assert projection["reconciled"]["withdrawnTeams"] == 0

    session.expire_all()
    after = _teams_by_key(session, imported.tournament_id)
    assert replacement.team_key in after
    new_team = after[replacement.team_key]
    assert list(after).count(replacement.team_key) == 1
    old = session.get(Team, withdrawn.id)
    assert old.is_defaulted is False
    session.refresh(match)
    session.refresh(advanced)
    assert match.team_a_id == old.id
    assert match.team_b_id == partner.id
    assert match.runtime_status == "FINAL"
    assert match.score_json == {"display": "4-2"}
    assert match.winner_team_id == old.id
    assert advanced.team_a_id == old.id
    assert advanced.source_match_a_id == match.id
    assert advanced.source_a_role == "WINNER"
    assert new_team.id not in {match.team_a_id, match.team_b_id, advanced.team_a_id, advanced.team_b_id}

    survivor_row = after[teams[1].team_key]
    assert survivor_row.player1_cellphone == "5557778888"
    assert survivor_row.player1_email == "survivor@example.com"
    towel = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == imported.tournament_id,
            TemporaryPlayerLookup.source_team_key == teams[1].team_key,
            TemporaryPlayerLookup.lineup_slot == 1,
        )
    ).first()
    assert towel.towel_color == "Lime"
    old_towels = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == imported.tournament_id,
            TemporaryPlayerLookup.source_team_key == teams[0].team_key,
        )
    ).all()
    assert len(old_towels) == 2
    new_towels = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == imported.tournament_id,
            TemporaryPlayerLookup.source_team_key == replacement.team_key,
        )
    ).all()
    assert {row.towel_color for row in new_towels} == {"Purple", "Gold"}


def test_staff_defaulted_team_leaves_active_lists_and_keeps_match_label(client: TestClient, session: Session):
    """Weekend default uses the same is_defaulted flag as an RW-OS withdrawal."""
    teams = _womens_field(8)
    imported = _import_payload(session, 942, teams)
    _approve(client, imported.id, {"womens": "8"})
    session.expire_all()
    live = _teams_by_key(session, imported.tournament_id)
    defaulted = live[teams[0].team_key]
    opponent = live[teams[1].team_key]
    active = live[teams[2].team_key]
    active_partner = live[teams[3].team_key]
    event = session.get(Event, defaulted.event_id)
    defaulted.is_defaulted = True
    session.add(defaulted)
    session.commit()

    finished = _assign_unplayed_wf_slot(session, imported.tournament_id, event, defaulted, opponent)
    finished.match_type = "RR"
    finished.match_code = "RR_FINAL_01"
    finished.runtime_status = "FINAL"
    finished.winner_team_id = opponent.id
    finished.score_json = {"display": "6-4 6-4"}
    session.add(finished)
    upcoming = Match(
        tournament_id=imported.tournament_id,
        event_id=event.id,
        schedule_version_id=finished.schedule_version_id,
        match_code="WF_R1_02",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=active.id,
        team_b_id=active_partner.id,
        placeholder_side_a=active.name,
        placeholder_side_b=active_partner.name,
    )
    session.add(upcoming)
    session.commit()
    session.refresh(upcoming)
    tournament = session.get(Tournament, imported.tournament_id)
    _schedule_match(session, tournament, upcoming)

    desk = client.get(f"/api/desk/tournaments/{imported.tournament_id}/teams")
    assert desk.status_code == 200, desk.text
    desk_ids = {row["team_id"] for row in desk.json()}
    assert defaulted.id not in desk_ids
    assert opponent.id in desk_ids

    sms = client.post(
        f"/api/tournaments/{imported.tournament_id}/sms/preview/event/{event.id}",
        json={"message": "Active roster"},
    )
    assert sms.status_code == 200, sms.text
    sms_ids = {row["team_id"] for row in sms.json()["recipients"]}
    assert defaulted.id not in sms_ids
    assert opponent.id in sms_ids

    wkw = client.get(f"/api/events/{event.id}/avoid-edges")
    assert wkw.status_code == 200, wkw.text
    assert all(edge["team_id_a"] != defaulted.id and edge["team_id_b"] != defaulted.id for edge in wkw.json())

    lens = client.get(f"/api/events/{event.id}/waterfall/conflicts")
    assert lens.status_code == 200, lens.text
    summary = lens.json()["graph_summary"]
    assert summary["team_count"] == 7
    assert all(row["team_id"] != defaulted.id for row in summary["top_degree_teams"])

    checkin = client.get(
        f"/api/desk/tournaments/{imported.tournament_id}/checkin/queue",
        params={"version_id": finished.schedule_version_id},
    )
    assert checkin.status_code == 200, checkin.text
    checkin_ids = set()
    for row in checkin.json()["checkin_matches"]:
        checkin_ids.add(row["side_a"]["team_id"])
        checkin_ids.add(row["side_b"]["team_id"])
    assert defaulted.id not in checkin_ids
    assert active.id in checkin_ids

    snapshot = client.get(
        f"/api/desk/tournaments/{imported.tournament_id}/snapshot",
        params={"version_id": finished.schedule_version_id},
    )
    assert snapshot.status_code == 200, snapshot.text
    finished_row = next(row for row in snapshot.json()["matches"] if row["match_id"] == finished.id)
    assert finished_row["team1_id"] == defaulted.id
    assert finished_row["team1_display"]
    assert finished_row["team1_defaulted"] is True
    assert finished_row["winner_team_id"] == opponent.id
    assert finished_row["score_display"]


def _draw_participant_ids(session: Session, event_id: int) -> set[int]:
    ids: set[int] = set()
    for match in session.exec(select(Match).where(Match.event_id == event_id)).all():
        if match.team_a_id is not None:
            ids.add(match.team_a_id)
        if match.team_b_id is not None:
            ids.add(match.team_b_id)
    return ids


def _wf_r1_match(
    session: Session,
    *,
    tournament_id: int,
    event: Event,
    version: ScheduleVersion,
    sequence: int,
    team_a: Team | None,
    team_b: Team | None,
    match_code: str | None = None,
    round_index: int = 1,
    match_type: str = "WF",
) -> Match:
    match = Match(
        tournament_id=tournament_id,
        event_id=event.id,
        schedule_version_id=version.id,
        match_code=match_code or f"MX_WF_R1_{sequence:02d}",
        match_type=match_type,
        round_number=round_index,
        round_index=round_index,
        sequence_in_round=sequence,
        duration_minutes=60,
        team_a_id=team_a.id if team_a else None,
        team_b_id=team_b.id if team_b else None,
        placeholder_side_a=team_a.name if team_a else "TBD",
        placeholder_side_b=team_b.name if team_b else "TBD",
    )
    session.add(match)
    session.commit()
    session.refresh(match)
    return match


def test_refresh_fills_existing_24_capacity_without_rebuilding_structure(client: TestClient, session: Session):
    """20 teams were placed into an already-built 24-team Mixed draw. Four later registrations fill the open sides."""
    initial = _mixed_field(20)
    imported = _import_payload(session, 943, initial)
    _approve(client, imported.id, {"mixed": "20"})
    session.expire_all()
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).one()
    plan = session.exec(select(TournamentDrawPlan).where(TournamentDrawPlan.import_id == imported.id)).one()
    brackets = json.loads(plan.brackets_json)
    brackets[0]["size"] = 24
    brackets[0]["rankEnd"] = 24
    plan.brackets_json = json.dumps(brackets)
    event.team_count = 24
    event.draw_status = "generated"
    session.add(plan)
    session.add(event)
    session.commit()

    live = _teams_by_key(session, imported.tournament_id)
    ordered = sorted(live.values(), key=lambda team: (team.seed is None, team.seed or 0, team.id or 0))
    assert len(ordered) == 20
    version = ScheduleVersion(tournament_id=imported.tournament_id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)
    filled = []
    for index in range(10):
        filled.append(
            _wf_r1_match(
                session,
                tournament_id=imported.tournament_id,
                event=event,
                version=version,
                sequence=index + 1,
                team_a=ordered[index * 2],
                team_b=ordered[index * 2 + 1],
            )
        )
    open_matches = [
        _wf_r1_match(
            session,
            tournament_id=imported.tournament_id,
            event=event,
            version=version,
            sequence=11,
            team_a=None,
            team_b=None,
        ),
        _wf_r1_match(
            session,
            tournament_id=imported.tournament_id,
            event=event,
            version=version,
            sequence=12,
            team_a=None,
            team_b=None,
        ),
    ]
    feeder = _wf_r1_match(
        session,
        tournament_id=imported.tournament_id,
        event=event,
        version=version,
        sequence=1,
        team_a=None,
        team_b=None,
        match_code="MX_WF_R2_01",
        round_index=2,
    )
    bye = _wf_r1_match(
        session,
        tournament_id=imported.tournament_id,
        event=event,
        version=version,
        sequence=13,
        team_a=None,
        team_b=None,
        match_code="MX_WF_R1_13_BYE",
    )
    tournament = session.get(Tournament, imported.tournament_id)
    _schedule_match(session, tournament, open_matches[0])
    before_ids = {match.id for match in session.exec(select(Match).where(Match.event_id == event.id)).all()}
    before_filled = {match.id: (match.team_a_id, match.team_b_id) for match in filled}
    assert len(_draw_participant_ids(session, event.id)) == 20

    additions = _mixed_field(4, start_id=1900, start_rating=6.0)
    for team in additions:
        team.avoid_group = "Q"
    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in initial] + additions
    persisted = persist_snapshot(
        session,
        _payload(943, refreshed, version="mixed-24"),
        existing=session.get(TournamentImport, imported.id),
    )
    projection = getattr(persisted, "_last_roster_projection", None) or {}
    assert projection["created"]["teams"] == 4
    assert projection["reconciled"]["drawSlotsReplaced"] == 4
    assert not any(item["code"] == "roster_draw_placement_unresolved" for item in projection["conflicts"])

    session.expire_all()
    event = session.get(Event, event.id)
    plan = session.get(TournamentDrawPlan, plan.id)
    assert event.team_count == 24
    assert json.loads(plan.brackets_json)[0]["size"] == 24
    assert json.loads(plan.brackets_json)[0]["rankEnd"] == 24
    after = _teams_by_key(session, imported.tournament_id)
    active = [team for team in after.values() if not team.is_defaulted]
    assert len(active) == 24
    assert len(after) == 24
    assert {team.event_id for team in active} == {event.id}
    assert _draw_participant_ids(session, event.id) == {team.id for team in active}
    match_ids = {match.id for match in session.exec(select(Match).where(Match.event_id == event.id)).all()}
    assert match_ids == before_ids
    for match in filled:
        session.refresh(match)
        assert (match.team_a_id, match.team_b_id) == before_filled[match.id]
    session.refresh(feeder)
    session.refresh(bye)
    assert feeder.team_a_id is None and feeder.team_b_id is None
    assert bye.team_a_id is None and bye.team_b_id is None
    new_ids = {after[team.team_key].id for team in additions}
    open_ids = set()
    for match in open_matches:
        session.refresh(match)
        open_ids.update(team_id for team_id in (match.team_a_id, match.team_b_id) if team_id is not None)
    assert open_ids == new_ids

    towels = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == imported.tournament_id,
            TemporaryPlayerLookup.source == "rwos-import",
        )
    ).all()
    towel_keys = {row.source_team_key for row in towels}
    assert {team.team_key for team in additions} <= towel_keys
    edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id)).all()
    edge_ids = {edge.team_id_a for edge in edges} | {edge.team_id_b for edge in edges}
    assert new_ids <= edge_ids

    desk = client.get(f"/api/desk/tournaments/{imported.tournament_id}/teams")
    assert desk.status_code == 200, desk.text
    assert new_ids <= {row["team_id"] for row in desk.json()}
    checkin = client.get(
        f"/api/desk/tournaments/{imported.tournament_id}/checkin/queue",
        params={"version_id": version.id},
    )
    assert checkin.status_code == 200, checkin.text
    checkin_ids = set()
    for row in checkin.json()["checkin_matches"]:
        checkin_ids.add(row["side_a"]["team_id"])
        checkin_ids.add(row["side_b"]["team_id"])
    assert new_ids & checkin_ids

    again = persist_snapshot(
        session,
        _payload(943, refreshed, version="mixed-24"),
        existing=session.get(TournamentImport, imported.id),
    )
    second = getattr(again, "_last_roster_projection", None) or {}
    assert second["created"]["teams"] == 0
    assert second["reconciled"]["drawSlotsReplaced"] == 0
    assert not any(item["code"] == "roster_draw_placement_unresolved" for item in second["conflicts"])
    session.expire_all()
    assert len(_teams_by_key(session, imported.tournament_id)) == 24
    assert _draw_participant_ids(session, event.id) == {team.id for team in active}


def test_refresh_withdrawals_and_replacements_keep_24_team_capacity(client: TestClient, session: Session):
    initial = _mixed_field(24)
    imported = _import_payload(session, 944, initial)
    _approve(client, imported.id, {"mixed": "24"})
    session.expire_all()
    event = session.exec(select(Event).where(Event.tournament_id == imported.tournament_id)).one()
    assert event.team_count == 24
    plan = session.exec(select(TournamentDrawPlan).where(TournamentDrawPlan.import_id == imported.id)).one()
    structure_before = plan.brackets_json
    live = _teams_by_key(session, imported.tournament_id)
    ordered = sorted(
        (team for team in live.values() if not team.is_defaulted),
        key=lambda team: (team.seed is None, team.seed or 0, team.id or 0),
    )
    version = ScheduleVersion(tournament_id=imported.tournament_id, version_number=1, status="draft")
    session.add(version)
    session.commit()
    session.refresh(version)
    matches = []
    for index in range(12):
        matches.append(
            _wf_r1_match(
                session,
                tournament_id=imported.tournament_id,
                event=event,
                version=version,
                sequence=index + 1,
                team_a=ordered[index],
                team_b=ordered[index + 12],
            )
        )
    before_ids = {match.id for match in matches}
    unchanged = {match.id: (match.team_a_id, match.team_b_id) for match in matches[4:]}
    withdrawn = [ordered[index] for index in range(4)]
    partners = {match.team_b_id for match in matches[:4]}
    kept_keys = {team.source_team_key for team in ordered[4:]}
    additions = _mixed_field(4, start_id=2900, start_rating=5.5)
    for team in additions:
        team.avoid_group = "Q"
    kept = [team for team in initial if team.team_key in kept_keys]
    refreshed = [SnapshotTeam.from_dict(team.to_dict()) for team in kept] + additions
    persisted = persist_snapshot(
        session,
        _payload(944, refreshed, version="mixed-24-replaced"),
        existing=session.get(TournamentImport, imported.id),
    )
    projection = getattr(persisted, "_last_roster_projection", None) or {}
    assert projection["created"]["teams"] == 4
    assert projection["reconciled"]["withdrawnTeams"] == 4
    assert projection["reconciled"]["drawSlotsReplaced"] == 4
    assert not any(
        item["code"] in {"roster_reconciliation_blocked", "roster_draw_placement_unresolved"}
        for item in projection["conflicts"]
    )

    session.expire_all()
    event = session.get(Event, event.id)
    plan = session.get(TournamentDrawPlan, plan.id)
    assert event.team_count == 24
    assert plan.brackets_json == structure_before
    after = _teams_by_key(session, imported.tournament_id)
    active = [team for team in after.values() if not team.is_defaulted]
    assert len(active) == 24
    assert len(after) == 28
    new_ids = {after[team.team_key].id for team in additions}
    assert _draw_participant_ids(session, event.id) == {team.id for team in active}
    assert new_ids <= _draw_participant_ids(session, event.id)
    match_ids = {match.id for match in session.exec(select(Match).where(Match.event_id == event.id)).all()}
    assert match_ids == before_ids
    for match in matches[4:]:
        session.refresh(match)
        assert (match.team_a_id, match.team_b_id) == unchanged[match.id]
    for match in matches[:4]:
        session.refresh(match)
        assert match.team_a_id in new_ids
        assert match.team_b_id in partners
        assert match.team_a_id != match.team_b_id
    for team in withdrawn:
        row = session.get(Team, team.id)
        assert row.is_defaulted is True
        assert row.id not in _draw_participant_ids(session, event.id)

    towels = session.exec(
        select(TemporaryPlayerLookup).where(
            TemporaryPlayerLookup.tournament_id == imported.tournament_id,
            TemporaryPlayerLookup.source == "rwos-import",
        )
    ).all()
    assert {team.team_key for team in additions} <= {row.source_team_key for row in towels}
    assert all(row.source_team_key not in {team.source_team_key for team in withdrawn} for row in towels)
    edges = session.exec(select(TeamAvoidEdge).where(TeamAvoidEdge.event_id == event.id)).all()
    edge_ids = {edge.team_id_a for edge in edges} | {edge.team_id_b for edge in edges}
    assert new_ids <= edge_ids
    assert all(team.id not in edge_ids for team in withdrawn)
