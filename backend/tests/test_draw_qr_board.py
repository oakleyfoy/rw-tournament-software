"""Read-only Draw QR Board API tests."""

from datetime import date

from sqlmodel import Session, delete

from app.models.auth_session import AuthSession
from app.models.event import Event
from app.models.match import Match
from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament
from app.models.user_account import UserAccount
from app.services.draw_qr_board import (
    public_bracket_path,
    public_round_robin_path,
    public_waterfall_path,
    tournament_filename_slug,
)
from app.utils.event_schedule_orders import serialize_event_schedule_day_orders


def _tournament(session: Session, name: str = "Racquet War Destin") -> Tournament:
    tournament = Tournament(
        name=name,
        location="Destin",
        timezone="America/Chicago",
        start_date=date(2026, 9, 12),
        end_date=date(2026, 9, 13),
    )
    session.add(tournament)
    session.flush()
    return tournament


def _version(session: Session, tournament_id: int, status: str = "final") -> ScheduleVersion:
    version = ScheduleVersion(
        tournament_id=tournament_id,
        version_number=1,
        status=status,
    )
    session.add(version)
    session.flush()
    return version


def _event(
    session: Session,
    tournament_id: int,
    name: str,
    category: str = "womens",
    team_count: int = 16,
    draw_plan_json: str | None = None,
) -> Event:
    event = Event(
        tournament_id=tournament_id,
        name=name,
        category=category,
        team_count=team_count,
        draw_status="final",
        draw_plan_json=draw_plan_json,
    )
    session.add(event)
    session.flush()
    return event


def _match(
    session: Session,
    *,
    tournament_id: int,
    event_id: int,
    version_id: int,
    match_code: str,
    match_type: str,
) -> Match:
    match = Match(
        tournament_id=tournament_id,
        event_id=event_id,
        schedule_version_id=version_id,
        match_code=match_code,
        match_type=match_type,
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
    )
    session.add(match)
    session.flush()
    return match


def test_mixed_draw_types_return_waterfall_rr_and_bracket(client, session, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://players.example.com")
    tournament = _tournament(session)
    version = _version(session, tournament.id)
    womens_a = _event(session, tournament.id, "Women's A", draw_plan_json='{"template_type":"WF_TO_POOLS_DYNAMIC"}')
    womens_b = _event(session, tournament.id, "Women's B", draw_plan_json='{"template_type":"RR_ONLY"}')
    mixed_a = _event(
        session,
        tournament.id,
        "Mixed A",
        category="mixed",
        team_count=32,
        draw_plan_json='{"template_type":"WF_TO_BRACKETS_8"}',
    )
    _match(
        session,
        tournament_id=tournament.id,
        event_id=womens_a.id,
        version_id=version.id,
        match_code="WA_WF_R1_01",
        match_type="WF",
    )
    _match(
        session,
        tournament_id=tournament.id,
        event_id=womens_b.id,
        version_id=version.id,
        match_code="WB_POOLA_RR_01",
        match_type="RR",
    )
    _match(
        session,
        tournament_id=tournament.id,
        event_id=mixed_a.id,
        version_id=version.id,
        match_code="MA_BWW_QF1",
        match_type="MAIN",
    )
    tournament.public_schedule_version_id = version.id
    tournament.event_schedule_day_orders_json = serialize_event_schedule_day_orders(
        [[womens_a.id, womens_b.id, mixed_a.id]]
    )
    session.commit()

    resp = client.get(f"/api/tournaments/{tournament.id}/draw-qr-board")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tournament_id"] == tournament.id
    assert body["tournament_name"] == "Racquet War Destin"
    assert body["filename_slug"] == "racquet-war-destin"
    types = [(item["label"], item["draw_type"], item["draw_type_label"]) for item in body["items"]]
    assert types == [
        ("Women's A", "waterfall", "Waterfall"),
        ("Women's B", "round_robin", "Round Robin"),
        ("Mixed A", "bracket", "Bracket"),
    ]
    urls = {item["draw_type"]: item["public_url"] for item in body["items"]}
    assert urls["waterfall"] == f"https://players.example.com{public_waterfall_path(tournament.id, womens_a.id)}"
    assert urls["round_robin"] == f"https://players.example.com{public_round_robin_path(tournament.id, womens_b.id)}"
    assert urls["bracket"] == f"https://players.example.com{public_bracket_path(tournament.id, mixed_a.id, 'BWW')}"
    assert body["items"][2]["public_path"] == public_bracket_path(tournament.id, mixed_a.id, "BWW")


def test_empty_event_without_generated_draw_is_omitted(client, session, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://players.example.com")
    tournament = _tournament(session)
    version = _version(session, tournament.id)
    _event(session, tournament.id, "Women's C")
    visible = _event(session, tournament.id, "Women's A")
    _match(
        session,
        tournament_id=tournament.id,
        event_id=visible.id,
        version_id=version.id,
        match_code="WA_WF_R1_01",
        match_type="WF",
    )
    tournament.public_schedule_version_id = version.id
    session.commit()

    body = client.get(f"/api/tournaments/{tournament.id}/draw-qr-board").json()
    assert [item["label"] for item in body["items"]] == ["Women's A"]


def test_unpublished_tournament_returns_empty_items(client, session, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://players.example.com")
    tournament = _tournament(session)
    version = _version(session, tournament.id)
    event = _event(session, tournament.id, "Women's A")
    _match(
        session,
        tournament_id=tournament.id,
        event_id=event.id,
        version_id=version.id,
        match_code="WA_WF_R1_01",
        match_type="WF",
    )
    session.commit()

    body = client.get(f"/api/tournaments/{tournament.id}/draw-qr-board").json()
    assert body["items"] == []


def test_one_event_can_return_multiple_public_draw_artifacts(client, session, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://players.example.com")
    tournament = _tournament(session)
    version = _version(session, tournament.id)
    event = _event(
        session,
        tournament.id,
        "Mixed A",
        category="mixed",
        team_count=32,
        draw_plan_json='{"template_type":"WF_TO_BRACKETS_8"}',
    )
    _match(
        session,
        tournament_id=tournament.id,
        event_id=event.id,
        version_id=version.id,
        match_code="MA_WF_R1_01",
        match_type="WF",
    )
    _match(
        session,
        tournament_id=tournament.id,
        event_id=event.id,
        version_id=version.id,
        match_code="MA_BWW_QF1",
        match_type="MAIN",
    )
    _match(
        session,
        tournament_id=tournament.id,
        event_id=event.id,
        version_id=version.id,
        match_code="MA_BWL_QF1",
        match_type="MAIN",
    )
    tournament.public_schedule_version_id = version.id
    session.commit()

    items = client.get(f"/api/tournaments/{tournament.id}/draw-qr-board").json()["items"]
    assert [(item["draw_type"], item["draw_type_label"], item["division_code"]) for item in items] == [
        ("waterfall", "Waterfall", None),
        ("bracket", "Division I", "BWW"),
        ("bracket", "Division II", "BWL"),
    ]
    assert items[1]["public_path"] == public_bracket_path(tournament.id, event.id, "BWW")
    assert items[2]["public_path"] == public_bracket_path(tournament.id, event.id, "BWL")


def test_pools_only_format_does_not_emit_stale_bracket_codes(client, session, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://players.example.com")
    tournament = _tournament(session)
    version = _version(session, tournament.id)
    event = _event(
        session,
        tournament.id,
        "Women's B",
        draw_plan_json='{"template_type":"WF_TO_POOLS_DYNAMIC"}',
    )
    _match(
        session,
        tournament_id=tournament.id,
        event_id=event.id,
        version_id=version.id,
        match_code="WB_WF_R1_01",
        match_type="WF",
    )
    _match(
        session,
        tournament_id=tournament.id,
        event_id=event.id,
        version_id=version.id,
        match_code="WB_POOLA_RR_01",
        match_type="RR",
    )
    _match(
        session,
        tournament_id=tournament.id,
        event_id=event.id,
        version_id=version.id,
        match_code="WB_BWW_QF1",
        match_type="MAIN",
    )
    tournament.public_schedule_version_id = version.id
    session.commit()

    items = client.get(f"/api/tournaments/{tournament.id}/draw-qr-board").json()["items"]
    assert [item["draw_type"] for item in items] == ["waterfall", "round_robin"]


def test_amelia_island_order_is_womens_abc_then_mixed_with_wf_before_rr(client, session, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://players.example.com")
    tournament = _tournament(session, "Amelia Island")
    version = _version(session, tournament.id)
    # Insert in scrambled order and give day_orders the wrong C→A sequence so
    # the QR board cannot be relying on insert order or schedule policy.
    mixed_b = _event(session, tournament.id, "Mixed B", category="mixed")
    womens_c = _event(session, tournament.id, "Women's C")
    mixed_a = _event(session, tournament.id, "Mixed A", category="mixed")
    womens_a = _event(session, tournament.id, "Women's A")
    womens_b = _event(session, tournament.id, "Women's B")
    for event in (mixed_b, womens_c, mixed_a, womens_a, womens_b):
        _match(
            session,
            tournament_id=tournament.id,
            event_id=event.id,
            version_id=version.id,
            match_code=f"E{event.id}_WF_R1_01",
            match_type="WF",
        )
        _match(
            session,
            tournament_id=tournament.id,
            event_id=event.id,
            version_id=version.id,
            match_code=f"E{event.id}_POOLA_RR_01",
            match_type="RR",
        )
    tournament.public_schedule_version_id = version.id
    tournament.event_schedule_day_orders_json = serialize_event_schedule_day_orders(
        [[womens_c.id, mixed_b.id, womens_a.id]]
    )
    session.commit()

    rows = [
        (item["label"], item["draw_type_label"])
        for item in client.get(f"/api/tournaments/{tournament.id}/draw-qr-board").json()["items"]
    ]
    assert rows == [
        ("Women's A", "Waterfall"),
        ("Women's A", "Round Robin"),
        ("Women's B", "Waterfall"),
        ("Women's B", "Round Robin"),
        ("Women's C", "Waterfall"),
        ("Women's C", "Round Robin"),
        ("Mixed A", "Waterfall"),
        ("Mixed A", "Round Robin"),
        ("Mixed B", "Waterfall"),
        ("Mixed B", "Round Robin"),
    ]


def test_brackets_stay_grouped_with_their_event_after_waterfall_and_rr(client, session, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://players.example.com")
    tournament = _tournament(session)
    version = _version(session, tournament.id)
    mixed_a = _event(
        session,
        tournament.id,
        "Mixed A",
        category="mixed",
        team_count=32,
        draw_plan_json='{"template_type":"WF_TO_BRACKETS_8"}',
    )
    womens_b = _event(
        session,
        tournament.id,
        "Women's B",
        team_count=32,
        draw_plan_json='{"template_type":"WF_TO_BRACKETS_8"}',
    )
    for event in (mixed_a, womens_b):
        _match(
            session,
            tournament_id=tournament.id,
            event_id=event.id,
            version_id=version.id,
            match_code=f"E{event.id}_WF_R1_01",
            match_type="WF",
        )
        _match(
            session,
            tournament_id=tournament.id,
            event_id=event.id,
            version_id=version.id,
            match_code=f"E{event.id}_POOLA_RR_01",
            match_type="RR",
        )
        _match(
            session,
            tournament_id=tournament.id,
            event_id=event.id,
            version_id=version.id,
            match_code=f"E{event.id}_BWW_QF1",
            match_type="MAIN",
        )
    tournament.public_schedule_version_id = version.id
    session.commit()

    rows = [
        (item["label"], item["draw_type_label"])
        for item in client.get(f"/api/tournaments/{tournament.id}/draw-qr-board").json()["items"]
    ]
    assert rows == [
        ("Women's B", "Waterfall"),
        ("Women's B", "Round Robin"),
        ("Women's B", "Bracket"),
        ("Mixed A", "Waterfall"),
        ("Mixed A", "Round Robin"),
        ("Mixed A", "Bracket"),
    ]


def test_draw_type_order_within_an_event_is_waterfall_rr_bracket(client, session, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://players.example.com")
    tournament = _tournament(session)
    version = _version(session, tournament.id)
    event = _event(
        session,
        tournament.id,
        "Women's B",
        team_count=32,
        draw_plan_json='{"template_type":"WF_TO_BRACKETS_8"}',
    )
    _match(
        session,
        tournament_id=tournament.id,
        event_id=event.id,
        version_id=version.id,
        match_code="WB_BWW_QF1",
        match_type="MAIN",
    )
    _match(
        session,
        tournament_id=tournament.id,
        event_id=event.id,
        version_id=version.id,
        match_code="WB_POOLA_RR_01",
        match_type="RR",
    )
    _match(
        session,
        tournament_id=tournament.id,
        event_id=event.id,
        version_id=version.id,
        match_code="WB_WF_R1_01",
        match_type="WF",
    )
    tournament.public_schedule_version_id = version.id
    session.commit()

    assert [
        item["draw_type"] for item in client.get(f"/api/tournaments/{tournament.id}/draw-qr-board").json()["items"]
    ] == [
        "waterfall",
        "round_robin",
        "bracket",
    ]


def test_other_tournament_draws_are_isolated(client, session, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://players.example.com")
    first = _tournament(session, "First Open")
    second = _tournament(session, "Second Open")
    first_version = _version(session, first.id)
    second_version = _version(session, second.id, status="final")
    second_version.version_number = 2
    session.add(second_version)
    first_event = _event(session, first.id, "Women's A")
    second_event = _event(session, second.id, "Mixed Spy")
    _match(
        session,
        tournament_id=first.id,
        event_id=first_event.id,
        version_id=first_version.id,
        match_code="FA_WF_R1_01",
        match_type="WF",
    )
    _match(
        session,
        tournament_id=second.id,
        event_id=second_event.id,
        version_id=second_version.id,
        match_code="SS_WF_R1_01",
        match_type="WF",
    )
    first.public_schedule_version_id = first_version.id
    second.public_schedule_version_id = second_version.id
    session.commit()

    items = client.get(f"/api/tournaments/{first.id}/draw-qr-board").json()["items"]
    assert [item["label"] for item in items] == ["Women's A"]
    assert all("Mixed Spy" not in item["label"] for item in items)
    assert all(f"/t/{first.id}/" in item["public_path"] for item in items)


def test_public_origin_prefers_env_over_localhost_request(client, session, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://players.example.com/api")
    tournament = _tournament(session)
    version = _version(session, tournament.id)
    event = _event(session, tournament.id, "Women's A")
    _match(
        session,
        tournament_id=tournament.id,
        event_id=event.id,
        version_id=version.id,
        match_code="WA_WF_R1_01",
        match_type="WF",
    )
    tournament.public_schedule_version_id = version.id
    session.commit()

    url = client.get(f"/api/tournaments/{tournament.id}/draw-qr-board").json()["items"][0]["public_url"]
    assert url.startswith("https://players.example.com/t/")
    assert "localhost" not in url
    assert "testserver" not in url
    assert "/api/" not in url


def test_missing_tournament_is_404(client, session):
    resp = client.get("/api/tournaments/999999/draw-qr-board")
    assert resp.status_code == 404


def test_draw_qr_board_is_get_only(client, session):
    tournament = _tournament(session)
    session.commit()
    assert client.post(f"/api/tournaments/{tournament.id}/draw-qr-board").status_code == 405
    assert client.patch(f"/api/tournaments/{tournament.id}/draw-qr-board").status_code == 405
    assert client.put(f"/api/tournaments/{tournament.id}/draw-qr-board").status_code == 405
    assert client.delete(f"/api/tournaments/{tournament.id}/draw-qr-board").status_code == 405


def test_staff_auth_required_after_bootstrap(client, session):
    session.exec(delete(AuthSession))
    session.exec(delete(UserAccount))
    session.commit()
    created = client.post(
        "/api/auth/bootstrap-admin",
        json={"username": "qradmin", "password": "password123", "display_name": "QR Admin"},
    )
    assert created.status_code == 201
    tournament = _tournament(session)
    session.commit()

    denied = client.get(f"/api/tournaments/{tournament.id}/draw-qr-board")
    assert denied.status_code == 401

    login = client.post("/api/auth/login", json={"username": "qradmin", "password": "password123"})
    token = login.json()["access_token"]
    allowed = client.get(
        f"/api/tournaments/{tournament.id}/draw-qr-board",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert allowed.status_code == 200


def test_filename_slug_falls_back_to_tournament_id():
    assert tournament_filename_slug("Destin September 2026", 9) == "destin-september-2026"
    assert tournament_filename_slug("@@@", 42) == "42"
