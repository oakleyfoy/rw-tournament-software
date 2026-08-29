from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.tournament_import import TournamentDrawPlan, TournamentImport


def _create_import(client: TestClient, source_id: int = 244) -> dict:
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


def test_a_imported_tournament_exposes_import_navigation(client: TestClient):
    created = _create_import(client)
    tournament_id = created["import"]["tournamentId"]
    import_id = created["import"]["id"]

    tournament = client.get(f"/api/tournaments/{tournament_id}")
    assert tournament.status_code == 200
    assert tournament.json()["rw_os_import_id"] == import_id
    # Tournament Setup shows Import / Draw Structure when rw_os_import_id is set.


def test_b_manual_tournament_has_no_import_navigation(client: TestClient):
    created = client.post(
        "/api/tournaments",
        json={
            "name": "Manual Tournament",
            "location": "Local",
            "timezone": "America/New_York",
            "start_date": "2026-08-01",
            "end_date": "2026-08-02",
        },
    )
    assert created.status_code == 201
    tournament_id = created.json()["id"]

    tournament = client.get(f"/api/tournaments/{tournament_id}")
    assert tournament.status_code == 200
    assert tournament.json()["rw_os_import_id"] is None
    missing = client.get(f"/api/rw-os/tournaments/{tournament_id}/import")
    assert missing.status_code == 404
    # Tournament Setup keeps the current navigation and hides Import / Draw Structure.


def test_c_navigation_resolves_the_existing_import(client: TestClient):
    first = _create_import(client, 244)
    second = _create_import(client, 148)
    first_tid = first["import"]["tournamentId"]
    second_tid = second["import"]["tournamentId"]

    first_import = client.get(f"/api/rw-os/tournaments/{first_tid}/import")
    second_import = client.get(f"/api/rw-os/tournaments/{second_tid}/import")
    assert first_import.status_code == 200
    assert second_import.status_code == 200
    assert first_import.json()["import"]["id"] == first["import"]["id"]
    assert second_import.json()["import"]["id"] == second["import"]["id"]
    assert first_import.json()["import"]["id"] != second_import.json()["import"]["id"]
    assert client.get(f"/api/tournaments/{first_tid}").json()["rw_os_import_id"] == first["import"]["id"]


def test_d_returning_after_approval_loads_selected_structure(client: TestClient):
    created = _create_import(client)
    import_id = created["import"]["id"]
    tournament_id = created["import"]["tournamentId"]
    approved = _approve_custom_womens(client, import_id, [20, 24])

    reopened = client.get(f"/api/rw-os/tournaments/{tournament_id}/import")
    assert reopened.status_code == 200
    body = reopened.json()
    assert body["import"]["id"] == import_id
    assert body["import"]["planStatus"] == "approved"
    assert body["approvedPlans"]
    assert body["selectedPlans"]
    assert body["selectedPlans"][0]["optionKey"] == "20-24"
    assert body["approvedPlans"][0]["optionKey"] == approved["approvedPlans"][0]["optionKey"]
    assert [event["name"] for event in body["tournamentEvents"]] == ["Women's A", "Women's B"]


def test_e_import_links_back_to_the_same_tournament(client: TestClient):
    created = _create_import(client)
    tournament_id = created["import"]["tournamentId"]
    reopened = client.get(f"/api/rw-os/tournaments/{tournament_id}/import")
    assert reopened.status_code == 200
    assert reopened.json()["import"]["tournamentId"] == tournament_id
    # Back to Tournament Setup uses /tournaments/{tournamentId}/setup.


def test_f_reopening_import_is_read_only(client: TestClient, session: Session):
    created = _create_import(client)
    import_id = created["import"]["id"]
    tournament_id = created["import"]["tournamentId"]
    _approve_custom_womens(client, import_id, [20, 24])

    before_import = session.get(TournamentImport, import_id)
    before_plans = session.exec(select(TournamentDrawPlan).where(TournamentDrawPlan.import_id == import_id)).all()
    before_events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
    before_matches = session.exec(select(Match).where(Match.tournament_id == tournament_id)).all()
    snapshot = {
        "updated_at": before_import.updated_at,
        "plan_status": before_import.plan_status,
        "approved_at": before_import.approved_at,
        "source_hash": before_import.source_hash,
        "plan_keys": {(plan.draw_kind, plan.option_key, plan.approved) for plan in before_plans},
        "event_rows": {(event.id, event.name, event.team_count) for event in before_events},
        "match_count": len(before_matches),
    }

    first = client.get(f"/api/rw-os/tournaments/{tournament_id}/import")
    second = client.get(f"/api/rw-os/imports/{import_id}")
    tournament = client.get(f"/api/tournaments/{tournament_id}")
    assert first.status_code == 200
    assert second.status_code == 200
    assert tournament.status_code == 200

    session.expire_all()
    after_import = session.get(TournamentImport, import_id)
    after_plans = session.exec(select(TournamentDrawPlan).where(TournamentDrawPlan.import_id == import_id)).all()
    after_events = session.exec(select(Event).where(Event.tournament_id == tournament_id)).all()
    after_matches = session.exec(select(Match).where(Match.tournament_id == tournament_id)).all()

    assert after_import.updated_at == snapshot["updated_at"]
    assert after_import.plan_status == snapshot["plan_status"]
    assert after_import.approved_at == snapshot["approved_at"]
    assert after_import.source_hash == snapshot["source_hash"]
    assert {(plan.draw_kind, plan.option_key, plan.approved) for plan in after_plans} == snapshot["plan_keys"]
    assert {(event.id, event.name, event.team_count) for event in after_events} == snapshot["event_rows"]
    assert len(after_matches) == snapshot["match_count"]
