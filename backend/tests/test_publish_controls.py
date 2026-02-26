"""
Phase A — Publish Controls tests.

Validates:
- Public endpoint returns NOT_PUBLISHED when no pointer set
- Publishing a FINAL version exposes it publicly
- Publishing a DRAFT version returns 400
- Unpublishing hides the schedule
- Switching the public version works deterministically
- Cannot publish a version from another tournament
"""

from datetime import date

import pytest
from sqlmodel import Session

from app.models.schedule_version import ScheduleVersion
from app.models.tournament import Tournament


def _make_tournament(session: Session, name: str = "Test Tournament") -> Tournament:
    t = Tournament(
        name=name,
        location="Test Location",
        timezone="America/New_York",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 3),
    )
    session.add(t)
    session.flush()
    return t


def _make_version(
    session: Session,
    tournament_id: int,
    version_number: int = 1,
    status: str = "draft",
) -> ScheduleVersion:
    v = ScheduleVersion(
        tournament_id=tournament_id,
        version_number=version_number,
        status=status,
    )
    session.add(v)
    session.flush()
    return v


def test_public_returns_not_published_when_no_pointer(client, session):
    """Public draws returns NOT_PUBLISHED when no public_schedule_version_id."""
    t = _make_tournament(session)
    _make_version(session, t.id, status="final")
    session.commit()

    resp = client.get(f"/api/public/tournaments/{t.id}/draws")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NOT_PUBLISHED"
    assert "message" in body


def test_publish_final_version_exposes_it(client, session):
    """Publishing a FINAL version makes it visible on public endpoints."""
    t = _make_tournament(session)
    v = _make_version(session, t.id, status="final")
    session.commit()

    pub_resp = client.patch(
        f"/api/tournaments/{t.id}/schedule/versions/{v.id}/publish"
    )
    assert pub_resp.status_code == 200
    pub_body = pub_resp.json()
    assert pub_body["success"] is True
    assert pub_body["public_schedule_version_id"] == v.id
    assert pub_body["version_status"] == "final"

    draws_resp = client.get(f"/api/public/tournaments/{t.id}/draws")
    assert draws_resp.status_code == 200
    draws_body = draws_resp.json()
    assert "status" not in draws_body or draws_body.get("status") != "NOT_PUBLISHED"
    assert "tournament_name" in draws_body


def test_publish_draft_returns_400(client, session):
    """Publishing a DRAFT version is rejected with 400."""
    t = _make_tournament(session)
    v = _make_version(session, t.id, status="draft")
    session.commit()

    resp = client.patch(
        f"/api/tournaments/{t.id}/schedule/versions/{v.id}/publish"
    )
    assert resp.status_code == 400
    assert "FINAL" in resp.json()["detail"]


def test_unpublish_hides_schedule(client, session):
    """Unpublishing clears the public pointer, returning NOT_PUBLISHED."""
    t = _make_tournament(session)
    v = _make_version(session, t.id, status="final")
    session.commit()

    client.patch(f"/api/tournaments/{t.id}/schedule/versions/{v.id}/publish")

    draws_resp = client.get(f"/api/public/tournaments/{t.id}/draws")
    assert draws_resp.status_code == 200
    assert draws_resp.json().get("status") != "NOT_PUBLISHED"

    unpub_resp = client.patch(f"/api/tournaments/{t.id}/schedule/unpublish")
    assert unpub_resp.status_code == 200
    assert unpub_resp.json()["success"] is True
    assert unpub_resp.json()["public_schedule_version_id"] is None

    draws_resp2 = client.get(f"/api/public/tournaments/{t.id}/draws")
    assert draws_resp2.status_code == 200
    assert draws_resp2.json()["status"] == "NOT_PUBLISHED"


def test_switch_public_version(client, session):
    """Switching the published version updates the public output."""
    t = _make_tournament(session)
    v1 = _make_version(session, t.id, version_number=1, status="final")
    v2 = _make_version(session, t.id, version_number=2, status="final")
    session.commit()

    client.patch(f"/api/tournaments/{t.id}/schedule/versions/{v1.id}/publish")

    resp1 = client.get(f"/api/tournaments/{t.id}")
    assert resp1.status_code == 200
    assert resp1.json()["public_schedule_version_id"] == v1.id

    client.patch(f"/api/tournaments/{t.id}/schedule/versions/{v2.id}/publish")

    resp2 = client.get(f"/api/tournaments/{t.id}")
    assert resp2.status_code == 200
    assert resp2.json()["public_schedule_version_id"] == v2.id


def test_cannot_publish_version_from_another_tournament(client, session):
    """Publishing a version that belongs to a different tournament is rejected."""
    t1 = _make_tournament(session, name="Tournament 1")
    t2 = _make_tournament(session, name="Tournament 2")
    v2 = _make_version(session, t2.id, status="final")
    session.commit()

    resp = client.patch(
        f"/api/tournaments/{t1.id}/schedule/versions/{v2.id}/publish"
    )
    assert resp.status_code == 404
    assert "does not belong" in resp.json()["detail"]
