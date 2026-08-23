"""One RW-OS event may source many independent Tournament Software imports."""

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlmodel import Session, select

from app.models.tournament import Tournament
from app.models.tournament_import import TournamentDrawPlan, TournamentImport
from app.services.rw_os_client import RwOsClient, RwOsReadOnlyError
from app.services.rw_os_fixtures import list_fixture_events

SOURCE_ID = 148
ISOLATION_SOURCE_ID = 244
HISTORICAL_ID = 101


def _event_ids(client: TestClient) -> set[int]:
    listed = client.get("/api/rw-os/events")
    assert listed.status_code == 200
    payload = listed.json()
    assert all("alreadyImported" not in event for event in payload["events"])
    return {event["tournamentId"] for event in payload["events"]}


def _import_event(client: TestClient, source_id: int = SOURCE_ID) -> dict:
    response = client.post("/api/rw-os/imports", json={"tournament_id": source_id, "organization_slug": "rw"})
    assert response.status_code == 201, response.text
    return response.json()


def test_a_no_existing_import_source_appears(client: TestClient):
    ids = _event_ids(client)
    assert SOURCE_ID in ids
    assert ISOLATION_SOURCE_ID in ids
    assert HISTORICAL_ID not in ids


def test_b_one_existing_import_source_still_appears(client: TestClient):
    created = _import_event(client)
    assert created["import"]["sourceTournamentId"] == SOURCE_ID
    assert SOURCE_ID in _event_ids(client)


def test_c_ten_existing_imports_source_still_appears(client: TestClient, session: Session):
    created = [_import_event(client, ISOLATION_SOURCE_ID) for _ in range(10)]
    import_ids = {row["import"]["id"] for row in created}
    tournament_ids = {row["import"]["tournamentId"] for row in created}
    assert len(import_ids) == 10
    assert len(tournament_ids) == 10
    rows = session.exec(
        select(TournamentImport).where(TournamentImport.source_tournament_id == ISOLATION_SOURCE_ID)
    ).all()
    assert len(rows) == 10
    tournaments = session.exec(
        select(Tournament).where(Tournament.source_rw_os_tournament_id == ISOLATION_SOURCE_ID)
    ).all()
    assert len(tournaments) == 10
    assert ISOLATION_SOURCE_ID in _event_ids(client)


def test_d_existing_ts_tournament_does_not_hide_source(client: TestClient, session: Session):
    created = _import_event(client)
    tournament = session.get(Tournament, created["import"]["tournamentId"])
    assert tournament is not None
    assert tournament.source_rw_os_tournament_id == SOURCE_ID
    assert SOURCE_ID in _event_ids(client)


def test_e_deleted_ts_tournament_source_still_appears(client: TestClient, session: Session):
    created = _import_event(client)
    import_id = created["import"]["id"]
    tournament_id = created["import"]["tournamentId"]
    deleted = client.delete(f"/api/tournaments/{tournament_id}")
    assert deleted.status_code == 204
    session.expire_all()
    assert session.get(Tournament, tournament_id) is None
    assert session.get(TournamentImport, import_id) is None
    assert session.exec(select(TournamentDrawPlan).where(TournamentDrawPlan.tournament_id == tournament_id)).all() == []
    assert SOURCE_ID in _event_ids(client)
    again = _import_event(client)
    assert again["import"]["sourceTournamentId"] == SOURCE_ID
    assert session.get(TournamentImport, again["import"]["id"]) is not None


def test_f_orphan_import_record_does_not_hide_source(client: TestClient, session: Session):
    created = _import_event(client)
    import_id = created["import"]["id"]
    tournament_id = created["import"]["tournamentId"]
    session.execute(text("PRAGMA foreign_keys=OFF"))
    session.execute(text("DELETE FROM tournament WHERE id = :id"), {"id": tournament_id})
    session.commit()
    session.expire_all()
    leftover = session.get(TournamentImport, import_id)
    assert leftover is not None
    assert leftover.source_tournament_id == SOURCE_ID
    assert leftover.tournament_id == tournament_id
    assert SOURCE_ID in _event_ids(client)


def test_g_two_ts_tournaments_keep_independent_imports(client: TestClient, session: Session):
    first = _import_event(client)
    second = _import_event(client)
    assert first["import"]["id"] != second["import"]["id"]
    assert first["import"]["tournamentId"] != second["import"]["tournamentId"]
    assert first["import"]["sourceTournamentId"] == SOURCE_ID
    assert second["import"]["sourceTournamentId"] == SOURCE_ID
    row_a = session.get(TournamentImport, first["import"]["id"])
    row_b = session.get(TournamentImport, second["import"]["id"])
    assert row_a is not None and row_b is not None
    assert row_a.tournament_id != row_b.tournament_id
    assert row_a.source_tournament_id == row_b.source_tournament_id == SOURCE_ID


def test_h_i_j_forecast_refresh_and_snapshot_isolation(client: TestClient, session: Session):
    first = _import_event(client, ISOLATION_SOURCE_ID)
    second = _import_event(client, ISOLATION_SOURCE_ID)
    import_a = first["import"]["id"]
    import_b = second["import"]["id"]
    hash_b = second["import"]["sourceHash"]
    snapshot_b = second["import"]["teams"]
    forecast_b = second["import"]["forecasts"]

    updated = client.put(f"/api/rw-os/imports/{import_a}/forecasts", json={"forecasts": {"womens": 50}})
    assert updated.status_code == 200
    assert updated.json()["import"]["forecasts"]["womens"] == 50
    other = client.get(f"/api/rw-os/imports/{import_b}")
    assert other.status_code == 200
    assert other.json()["import"]["forecasts"] == forecast_b
    assert other.json()["import"]["forecasts"]["womens"] != 50

    option_key = updated.json()["planner"]["draws"][0]["options"][0]["optionKey"]
    selected = client.post(
        f"/api/rw-os/imports/{import_a}/select-structure",
        json={"draw_kind": "womens", "option_key": option_key},
    )
    assert selected.status_code == 200
    assert selected.json()["selectedPlans"]
    other = client.get(f"/api/rw-os/imports/{import_b}")
    assert other.json()["selectedPlans"] == []
    plans_b = session.exec(select(TournamentDrawPlan).where(TournamentDrawPlan.import_id == import_b)).all()
    assert plans_b == []

    applied = client.post(f"/api/rw-os/imports/{import_a}/refresh", json={"apply": True})
    assert applied.status_code == 200
    assert applied.json()["applied"] is True
    session.expire_all()
    row_a = session.get(TournamentImport, import_a)
    row_b = session.get(TournamentImport, import_b)
    assert row_a is not None and row_b is not None
    assert row_a.source_hash != hash_b
    assert row_b.source_hash == hash_b
    other = client.get(f"/api/rw-os/imports/{import_b}")
    assert other.json()["import"]["sourceHash"] == hash_b
    assert other.json()["import"]["teams"] == snapshot_b
    assert other.json()["import"]["forecasts"] == forecast_b
    assert other.json()["selectedPlans"] == []


def test_k_closed_historical_rw_os_event_excluded(client: TestClient):
    fixture_ids = {event["tournamentId"] for event in list_fixture_events(include_historical=False)}
    assert HISTORICAL_ID not in fixture_ids
    assert HISTORICAL_ID not in _event_ids(client)


def test_l_open_rw_os_event_included_regardless_of_import_count(client: TestClient):
    for _ in range(3):
        _import_event(client, ISOLATION_SOURCE_ID)
    ids = _event_ids(client)
    assert ISOLATION_SOURCE_ID in ids
    assert SOURCE_ID in ids
    assert HISTORICAL_ID not in ids


def test_m_rw_os_writes_remain_zero(client: TestClient):
    created = _import_event(client)
    assert created["rwOsWrites"] == 0
    rw_os = RwOsClient(fixtures=True)
    try:
        rw_os._request("POST", "/api/integrations/tournament-software/events")
        assert False, "write should be rejected"
    except RwOsReadOnlyError:
        pass
    assert "POST" not in {method.upper() for method in ("GET",)}


def test_source_columns_are_not_unique():
    tournament_col = inspect(Tournament).columns["source_rw_os_tournament_id"]
    import_col = inspect(TournamentImport).columns["source_tournament_id"]
    assert tournament_col.unique is False
    assert import_col.unique is False
    assert Tournament.__table__.c.source_rw_os_tournament_id.unique is not True
    assert TournamentImport.__table__.c.source_tournament_id.unique is not True
