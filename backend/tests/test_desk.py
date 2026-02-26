"""
Phase C — Desk Runtime Console tests.

Validates:
- Working draft clones from published version
- Working draft is idempotent
- Finalize rejects FINAL version
- Finalize sets match FINAL and advances downstream
- Finalize idempotent with same payload
- Finalize warns on downstream conflict
- Snapshot returns court grouping
"""

from datetime import date, time

import pytest
from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.match_lock import MatchLock
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament


def _setup_tournament_with_matches(session: Session):
    """Create a published tournament with WF R1 matches wired to R2."""
    t = Tournament(
        name="Desk Test",
        location="Test Beach",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(
        tournament_id=t.id,
        version_number=1,
        status="final",
    )
    session.add(v)
    session.flush()

    ev = Event(
        tournament_id=t.id,
        category="womens",
        name="Women's A",
        team_count=4,
    )
    session.add(ev)
    session.flush()

    team1 = Team(event_id=ev.id, name="Alpha - VA", seed=1, display_name="Alpha")
    team2 = Team(event_id=ev.id, name="Bravo - NC", seed=2, display_name="Bravo")
    team3 = Team(event_id=ev.id, name="Charlie - FL", seed=3, display_name="Charlie")
    team4 = Team(event_id=ev.id, name="Delta - TX", seed=4, display_name="Delta")
    session.add_all([team1, team2, team3, team4])
    session.flush()

    # R1 Match 1: Alpha vs Delta
    m1 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_E1_WF_R1_M01",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team1.id,
        team_b_id=team4.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 4",
    )
    # R1 Match 2: Bravo vs Charlie
    m2 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_E1_WF_R1_M02",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=team2.id,
        team_b_id=team3.id,
        placeholder_side_a="Seed 2",
        placeholder_side_b="Seed 3",
    )
    session.add_all([m1, m2])
    session.flush()

    # R2 Match: Winner of M1 vs Winner of M2
    m3 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_E1_WF_R2_M01",
        match_type="WF",
        round_number=2,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="Winner M1",
        placeholder_side_b="Winner M2",
        source_match_a_id=m1.id,
        source_match_b_id=m2.id,
        source_a_role="WINNER",
        source_b_role="WINNER",
    )
    session.add(m3)
    session.flush()

    # Create slots and assignments
    slot1 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 6, 5),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    slot2 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 6, 5),
        start_time=time(9, 0),
        end_time=time(10, 0),
        court_number=2,
        court_label="2",
        block_minutes=60,
    )
    slot3 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 6, 5),
        start_time=time(11, 0),
        end_time=time(12, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add_all([slot1, slot2, slot3])
    session.flush()

    a1 = MatchAssignment(schedule_version_id=v.id, match_id=m1.id, slot_id=slot1.id)
    a2 = MatchAssignment(schedule_version_id=v.id, match_id=m2.id, slot_id=slot2.id)
    a3 = MatchAssignment(schedule_version_id=v.id, match_id=m3.id, slot_id=slot3.id)
    session.add_all([a1, a2, a3])
    session.flush()

    # Publish
    t.public_schedule_version_id = v.id
    session.add(t)
    session.commit()

    return t, v, ev, [team1, team2, team3, team4], [m1, m2, m3]


def test_working_draft_clones_from_published(client, session):
    """Working draft clones from published version and has same match count."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] is True
    assert body["status"] == "draft"
    assert body["notes"] == "Desk Draft"

    draft_id = body["version_id"]
    assert draft_id != v.id

    # Verify match count matches source
    snap_resp = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}")
    assert snap_resp.status_code == 200
    snap = snap_resp.json()
    assert len(snap["matches"]) == len(matches)


def test_working_draft_idempotent(client, session):
    """Calling working-draft twice returns the same version."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    resp1 = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    assert resp1.status_code == 200
    vid1 = resp1.json()["version_id"]
    assert resp1.json()["created"] is True

    resp2 = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    assert resp2.status_code == 200
    vid2 = resp2.json()["version_id"]
    assert resp2.json()["created"] is False

    assert vid1 == vid2


def test_finalize_rejects_final_version(client, session):
    """Cannot finalize a match in a FINAL version."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{matches[0].id}/finalize",
        json={
            "version_id": v.id,
            "score": "8-4",
            "winner_team_id": teams[0].id,
        },
    )
    assert resp.status_code == 400
    assert "FINAL" in resp.json()["detail"]


def test_finalize_sets_match_final_and_advances(client, session):
    """Finalizing an R1 match populates team in downstream R2."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    # Create desk draft
    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    # Find draft's M1 match (cloned)
    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    draft_m3 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    # M3 should have no teams initially
    assert draft_m3["team1_id"] is None
    assert draft_m3["team2_id"] is None

    # Finalize M1 with team1 (Alpha) as winner
    fin_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/finalize",
        json={
            "version_id": draft_id,
            "score": "8-4",
            "winner_team_id": draft_m1["team1_id"],
        },
    )
    assert fin_resp.status_code == 200
    fin_body = fin_resp.json()
    assert fin_body["match"]["status"] == "FINAL"
    assert fin_body["match"]["score_display"] == "8-4"

    # Downstream should be populated
    assert len(fin_body["downstream_updates"]) >= 1
    updated_match_ids = [u["match_id"] for u in fin_body["downstream_updates"]]
    assert draft_m3["match_id"] in updated_match_ids

    # Verify via snapshot
    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m3_after = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]
    assert m3_after["team1_id"] == draft_m1["team1_id"]


def test_finalize_idempotent_same_payload(client, session):
    """Finalizing the same match twice with same payload is a no-op."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    payload = {
        "version_id": draft_id,
        "score": "8-4",
        "winner_team_id": draft_m1["team1_id"],
    }

    resp1 = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/finalize",
        json=payload,
    )
    assert resp1.status_code == 200

    resp2 = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/finalize",
        json=payload,
    )
    assert resp2.status_code == 200
    assert resp2.json()["match"]["status"] == "FINAL"


def test_finalize_warns_on_downstream_conflict(client, session):
    """Returns warning if downstream slot already has a different team."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    draft_m3 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    # Manually set M3.team_a to a different team to create conflict
    m3_obj = session.get(Match, draft_m3["match_id"])
    m3_obj.team_a_id = draft_m1["team2_id"]  # Set to losing team
    session.add(m3_obj)
    session.commit()

    # Finalize M1 - winner should conflict with already-set team_a
    fin_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/finalize",
        json={
            "version_id": draft_id,
            "score": "8-4",
            "winner_team_id": draft_m1["team1_id"],
        },
    )
    assert fin_resp.status_code == 200
    body = fin_resp.json()
    assert len(body["warnings"]) >= 1
    assert body["warnings"][0]["reason"] == "CONFLICT_EXISTING_TEAM"


def test_snapshot_returns_court_grouping(client, session):
    """Snapshot includes now_playing and up_next per court."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    # Create desk draft and set a match IN_PROGRESS
    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    # Set M1 in progress
    status_resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )
    assert status_resp.status_code == 200

    # Get snapshot again
    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()

    assert "courts" in snap2
    assert len(snap2["courts"]) >= 1
    assert "now_playing_by_court" in snap2
    assert "up_next_by_court" in snap2

    # Court 1 should have M1 as now_playing
    assert "Court 1" in snap2["now_playing_by_court"]
    assert snap2["now_playing_by_court"]["Court 1"]["match_id"] == draft_m1["match_id"]

    # Court 1 should have M3 (11:00 AM) as up_next
    assert "Court 1" in snap2["up_next_by_court"]


def test_board_excludes_finals(client, session):
    """Board slots should not include FINAL matches."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    # Finalize M1
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": draft_m1["team1_id"]},
    )

    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    board = snap2["board_by_court"]
    court1 = [c for c in board if c["court_name"] == "Court 1"][0]

    # M1 is now FINAL, so it should NOT appear in any board slot
    if court1["now_playing"]:
        assert court1["now_playing"]["match_id"] != draft_m1["match_id"]
    if court1["up_next"]:
        assert court1["up_next"]["match_id"] != draft_m1["match_id"]
    if court1["on_deck"]:
        assert court1["on_deck"]["match_id"] != draft_m1["match_id"]


def test_board_shows_in_progress_as_now_playing(client, session):
    """Board now_playing should show the IN_PROGRESS match."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    draft_m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    # Set M1 in progress
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{draft_m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    board = snap2["board_by_court"]
    court1 = [c for c in board if c["court_name"] == "Court 1"][0]

    assert court1["now_playing"] is not None
    assert court1["now_playing"]["match_id"] == draft_m1["match_id"]
    assert court1["now_playing"]["status"] == "IN_PROGRESS"

    # up_next should be M3 (the 11:00 AM match on Court 1)
    assert court1["up_next"] is not None
    assert court1["up_next"]["match_id"] != draft_m1["match_id"]


def test_board_empty_court(client, session):
    """Courts with no non-final matches show all null board slots."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    board = snap["board_by_court"]

    # All courts should have board entries
    assert len(board) == len(snap["courts"])
    for entry in board:
        assert "court_name" in entry
        assert "now_playing" in entry
        assert "up_next" in entry
        assert "on_deck" in entry


# ── On Deck tests ──────────────────────────────────────────────────────

def test_on_deck_three_scheduled_matches(client, session):
    """Court with 3 scheduled matches: up_next = earliest, on_deck = second earliest."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    # Add a 4th match on Court 1 at 13:00 so Court 1 now has: M1 (9:00), M3 (11:00), M4 (13:00)
    m4 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=draft_id,
        match_code="WOM_E1_WF_R3_M01",
        match_type="WF",
        round_number=3,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[1].id,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
    )
    session.add(m4)
    session.flush()

    slot4 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=draft_id,
        day_date=date(2026, 6, 5),
        start_time=time(13, 0),
        end_time=time(14, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add(slot4)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=draft_id, match_id=m4.id, slot_id=slot4.id))
    session.commit()

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()

    # Court 1 on_deck_by_court should be M3 (11:00) — M1 (9:00) is up_next
    assert "on_deck_by_court" in snap
    court1_on_deck = snap["on_deck_by_court"].get("Court 1")
    court1_up_next = snap["up_next_by_court"].get("Court 1")

    assert court1_up_next is not None
    assert court1_on_deck is not None
    # up_next should be earliest (9:00), on_deck should be next (11:00)
    assert court1_up_next["sort_time"] <= court1_on_deck["sort_time"]


def test_on_deck_with_in_progress(client, session):
    """Court with IN_PROGRESS match: now_playing set, up_next and on_deck shift."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    # Add a 4th match on Court 1 at 13:00
    m4 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=draft_id,
        match_code="WOM_E1_WF_R3_M01",
        match_type="WF",
        round_number=3,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=teams[0].id,
        team_b_id=teams[1].id,
        placeholder_side_a="TBD",
        placeholder_side_b="TBD",
    )
    session.add(m4)
    session.flush()

    slot4 = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=draft_id,
        day_date=date(2026, 6, 5),
        start_time=time(13, 0),
        end_time=time(14, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add(slot4)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=draft_id, match_id=m4.id, slot_id=slot4.id))
    session.commit()

    # Set M1 (9:00 Court 1) to IN_PROGRESS
    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()

    assert snap2["now_playing_by_court"].get("Court 1") is not None
    assert snap2["now_playing_by_court"]["Court 1"]["match_id"] == m1["match_id"]

    # up_next should be M3 (11:00), on_deck should be M4 (13:00)
    assert snap2["up_next_by_court"].get("Court 1") is not None
    assert snap2["on_deck_by_court"].get("Court 1") is not None
    assert snap2["up_next_by_court"]["Court 1"]["sort_time"] < snap2["on_deck_by_court"]["Court 1"]["sort_time"]


# ── Impact endpoint tests ──────────────────────────────────────────────

def test_impact_terminal_match_null_targets(client, session):
    """R2 match (no downstream) returns null winner/loser targets."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    r2 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    resp = client.get(
        f"/api/desk/tournaments/{t.id}/impact?version_id={draft_id}&match_id={r2['match_id']}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["impacts"]) == 1
    imp = body["impacts"][0]
    assert imp["winner_target"] is None
    assert imp["loser_target"] is None


def test_impact_normal_match_shows_both_targets(client, session):
    """R1 matches that feed R2 show winner targets with correct slot mapping."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    resp = client.get(f"/api/desk/tournaments/{t.id}/impact?version_id={draft_id}")
    assert resp.status_code == 200
    body = resp.json()

    # Find R1 M1 impact
    m1_imp = [i for i in body["impacts"] if i["match_code"] == "WOM_E1_WF_R1_M01"][0]
    assert m1_imp["winner_target"] is not None
    assert m1_imp["winner_target"]["target_slot"] == "team_a"
    assert m1_imp["winner_target"]["blocked_reason"] is None

    # Find R1 M2 impact
    m2_imp = [i for i in body["impacts"] if i["match_code"] == "WOM_E1_WF_R1_M02"][0]
    assert m2_imp["winner_target"] is not None
    assert m2_imp["winner_target"]["target_slot"] == "team_b"
    assert m2_imp["winner_target"]["blocked_reason"] is None

    # R2 has no downstream
    r2_imp = [i for i in body["impacts"] if i["match_code"] == "WOM_E1_WF_R2_M01"][0]
    assert r2_imp["winner_target"] is None


def test_impact_locked_slot_shows_blocked(client, session):
    """If downstream match is locked, impact shows SLOT_LOCKED."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    # Find the draft R2 match and its slot
    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    r2 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    # Find the slot for R2
    draft_version_matches = session.exec(
        select(Match).where(Match.schedule_version_id == draft_id)
    ).all()
    r2_match = [m for m in draft_version_matches if m.match_code == "WOM_E1_WF_R2_M01"][0]
    assignment = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == draft_id,
            MatchAssignment.match_id == r2_match.id,
        )
    ).first()

    # Lock the R2 match
    lock = MatchLock(
        schedule_version_id=draft_id,
        match_id=r2_match.id,
        slot_id=assignment.slot_id,
    )
    session.add(lock)
    session.commit()

    # Check impact for R1 M1 — its winner target (R2) should be SLOT_LOCKED
    resp = client.get(
        f"/api/desk/tournaments/{t.id}/impact?version_id={draft_id}"
    )
    assert resp.status_code == 200
    body = resp.json()

    m1_imp = [i for i in body["impacts"] if i["match_code"] == "WOM_E1_WF_R1_M01"][0]
    assert m1_imp["winner_target"] is not None
    assert m1_imp["winner_target"]["blocked_reason"] == "SLOT_LOCKED"


# ── Conflict check tests ──────────────────────────────────────────────

def test_conflict_team_already_playing(client, session):
    """If a team is IN_PROGRESS in another match, warn TEAM_ALREADY_PLAYING."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    m3 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    # Finalize M1 so winner (Alpha) advances to M3's team_a slot
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": m1["team1_id"]},
    )

    # Set M3 (which now has Alpha in team_a) to IN_PROGRESS
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m3['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    # Now check M1 again (Alpha is still in M1's team_a and M3 is IN_PROGRESS for Alpha)
    # Use a fresh match that also has the same team — but our test setup only has Alpha in M1 and M3.
    # Check conflicts for setting M1 IN_PROGRESS (Alpha is already playing M3)
    # M1 is already FINAL so let's check M3 first scenario differently.

    # Actually: Alpha is in both M1 (FINAL) and M3 (IN_PROGRESS).
    # We need a scenario where a team is IN_PROGRESS in one match and we try to start another.
    # M2 has teams Bravo and Charlie. Let's make another match with Bravo.
    # Easier: set M2 IN_PROGRESS (Bravo/Charlie), then check conflicts for M3 which
    # doesn't have Bravo. Let's instead check M1-based scenario:

    # Reload snap to see updated state
    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m2 = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R1_M02"][0]

    # Set M2 IN_PROGRESS (Bravo vs Charlie)
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m2['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    # M3 now has Alpha (from advancement) — but M3 also has source_b from M2.
    # After M2 finalize, winner goes to M3 team_b. But M2 is only IN_PROGRESS, not finalized.
    # So M3 still has no team_b. But checking conflicts for M3: Alpha is in M3 and M3 is already IN_PROGRESS.
    # Let's check conflicts for M2 to see if Bravo or Charlie are in another IN_PROGRESS match.
    # They aren't. So let's use a different approach:

    # Simplest: M3 is IN_PROGRESS (Alpha). Check conflicts for M1 with Alpha.
    # But M1 is FINAL. Check conflicts for a SCHEDULED match with Alpha would work if one existed.

    # The cleanest test: just add another match with Alpha/Delta scheduled on same version.
    draft_matches = session.exec(
        select(Match).where(Match.schedule_version_id == draft_id)
    ).all()
    # Find Alpha's team ID (team1 of M1)
    alpha_id = m1["team1_id"]

    # Create a new match in the draft with Alpha
    new_match = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=draft_id,
        match_code="WOM_E1_TEST_EXTRA",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=99,
        duration_minutes=60,
        team_a_id=alpha_id,
        placeholder_side_a="Alpha",
        placeholder_side_b="TBD",
    )
    session.add(new_match)
    session.flush()

    # Create a slot and assignment for the new match
    new_slot = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=draft_id,
        day_date=date(2026, 6, 5),
        start_time=time(11, 0),
        end_time=time(12, 0),
        court_number=3,
        court_label="3",
        block_minutes=60,
    )
    session.add(new_slot)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=draft_id, match_id=new_match.id, slot_id=new_slot.id))
    session.commit()

    # Alpha is IN_PROGRESS in M3. Check conflicts for new_match (also has Alpha).
    resp = client.post(
        f"/api/desk/tournaments/{t.id}/conflicts/check",
        json={"version_id": draft_id, "action_type": "SET_IN_PROGRESS", "match_id": new_match.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    codes = [c["code"] for c in body["conflicts"]]
    assert "TEAM_ALREADY_PLAYING" in codes


def test_conflict_day_cap_exceeded(client, session):
    """If a team already has 2 FINAL/IN_PROGRESS matches on same day, warn DAY_CAP_EXCEEDED."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    m2 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M02"][0]
    alpha_id = m1["team1_id"]

    # Finalize M1 (Alpha wins) — Alpha has 1 FINAL match on Day 1
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": alpha_id},
    )

    # M3 has Alpha advanced. Set M3 IN_PROGRESS — Alpha now has 1 FINAL + 1 IN_PROGRESS = 2 on Day 1
    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m3 = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]

    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m3['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    # Now add a 3rd match for Alpha on the same day
    new_match = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=draft_id,
        match_code="WOM_E1_DAY_CAP_TEST",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=99,
        duration_minutes=60,
        team_a_id=alpha_id,
        placeholder_side_a="Alpha",
        placeholder_side_b="TBD",
    )
    session.add(new_match)
    session.flush()

    new_slot = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=draft_id,
        day_date=date(2026, 6, 5),
        start_time=time(14, 0),
        end_time=time(15, 0),
        court_number=3,
        court_label="3",
        block_minutes=60,
    )
    session.add(new_slot)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=draft_id, match_id=new_match.id, slot_id=new_slot.id))
    session.commit()

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/conflicts/check",
        json={"version_id": draft_id, "action_type": "SET_IN_PROGRESS", "match_id": new_match.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    codes = [c["code"] for c in body["conflicts"]]
    assert "DAY_CAP_EXCEEDED" in codes
    cap_warning = [c for c in body["conflicts"] if c["code"] == "DAY_CAP_EXCEEDED"][0]
    assert cap_warning["details"]["count"] == 3


def test_conflict_rest_too_short(client, session):
    """If rest time between matches < MIN_REST_MINUTES, warn REST_TOO_SHORT."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    alpha_id = m1["team1_id"]

    # Finalize M1 at 9:00 (Alpha wins). M1 slot: 9:00-10:00 (60 min block)
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": alpha_id},
    )

    # Create a match for Alpha starting at 10:15 — only 15 min rest after 10:00 end
    new_match = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=draft_id,
        match_code="WOM_E1_REST_TEST",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=99,
        duration_minutes=60,
        team_a_id=alpha_id,
        placeholder_side_a="Alpha",
        placeholder_side_b="TBD",
    )
    session.add(new_match)
    session.flush()

    new_slot = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=draft_id,
        day_date=date(2026, 6, 5),
        start_time=time(10, 15),
        end_time=time(11, 15),
        court_number=3,
        court_label="3",
        block_minutes=60,
    )
    session.add(new_slot)
    session.flush()
    session.add(MatchAssignment(schedule_version_id=draft_id, match_id=new_match.id, slot_id=new_slot.id))
    session.commit()

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/conflicts/check",
        json={"version_id": draft_id, "action_type": "SET_IN_PROGRESS", "match_id": new_match.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    codes = [c["code"] for c in body["conflicts"]]
    assert "REST_TOO_SHORT" in codes
    rest_warning = [c for c in body["conflicts"] if c["code"] == "REST_TOO_SHORT"][0]
    assert rest_warning["details"]["rest_minutes"] == 15


# ── Timeline tests ──────────────────────────────────────────────────────

def test_timeline_created_at_present(client, session):
    """Every match in snapshot has created_at timestamp."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    for m in snap["matches"]:
        assert m["created_at"] is not None
        assert m["started_at"] is None
        assert m["completed_at"] is None
        assert m["winner_display"] is None


def test_timeline_in_progress_sets_started_at(client, session):
    """Setting IN_PROGRESS sets started_at and preserves it on re-call."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1_after = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    assert m1_after["started_at"] is not None
    first_started = m1_after["started_at"]

    # Set IN_PROGRESS again — started_at should not change
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    snap3 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1_again = [m for m in snap3["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    assert m1_again["started_at"] == first_started


def test_timeline_finalize_sets_completed_at_and_winner(client, session):
    """Finalizing sets completed_at and winner_display. Re-finalize preserves timestamps."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": m1["team1_id"]},
    )

    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1_after = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    assert m1_after["completed_at"] is not None
    assert m1_after["winner_display"] is not None
    assert m1_after["status"] == "FINAL"
    first_completed = m1_after["completed_at"]

    # Re-finalize same payload — completed_at should not change
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": m1["team1_id"]},
    )

    snap3 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1_again = [m for m in snap3["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    assert m1_again["completed_at"] == first_completed


# ── Bulk Status tests ──────────────────────────────────────────────────

def test_bulk_pause_updates_in_progress_only(client, session):
    """Bulk pause sets only IN_PROGRESS matches to PAUSED, rejects FINAL version."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    m2 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M02"][0]

    # Set m1 to IN_PROGRESS
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    # Bulk pause
    resp = client.post(
        f"/api/desk/tournaments/{t.id}/bulk/pause-in-progress",
        json={"version_id": draft_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated_count"] == 1
    assert m1["match_id"] in body["updated_match_numbers"]

    # Verify m1 is PAUSED, m2 still SCHEDULED
    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1_after = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]
    m2_after = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R1_M02"][0]
    assert m1_after["status"] == "PAUSED"
    assert m2_after["status"] == "SCHEDULED"

    # Reject FINAL version
    resp2 = client.post(
        f"/api/desk/tournaments/{t.id}/bulk/pause-in-progress",
        json={"version_id": v.id},
    )
    assert resp2.status_code == 400


def test_bulk_delay_after_updates_scheduled_only(client, session):
    """Bulk delay-after sets SCHEDULED matches at or after threshold to DELAYED."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    # Set m1 to IN_PROGRESS so it won't be delayed
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "IN_PROGRESS"},
    )

    # Delay all scheduled matches after 10:00 — m2 (9:00) should NOT be delayed, m3 (11:00) should be
    resp = client.post(
        f"/api/desk/tournaments/{t.id}/bulk/delay-after",
        json={"version_id": draft_id, "after_time": "10:00"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated_count"] >= 1

    snap2 = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m2_after = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R1_M02"][0]
    m3_after = [m for m in snap2["matches"] if m["match_code"] == "WOM_E1_WF_R2_M01"][0]
    assert m2_after["status"] == "SCHEDULED"  # 9:00 AM, before threshold
    assert m3_after["status"] == "DELAYED"  # 11:00 AM, at or after threshold

    # Reject FINAL version
    resp2 = client.post(
        f"/api/desk/tournaments/{t.id}/bulk/delay-after",
        json={"version_id": v.id, "after_time": "10:00"},
    )
    assert resp2.status_code == 400


def test_bulk_delay_respects_day_index(client, session):
    """Delay-after with day_index filter only affects matches on that day."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    # All test matches are on day 1, so day_index=2 should affect nothing
    resp = client.post(
        f"/api/desk/tournaments/{t.id}/bulk/delay-after",
        json={"version_id": draft_id, "after_time": "08:00", "day_index": 2},
    )
    assert resp.status_code == 200
    assert resp.json()["updated_count"] == 0


def test_paused_delayed_status_via_status_endpoint(client, session):
    """The status endpoint accepts PAUSED and DELAYED as valid statuses."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    m1 = [m for m in snap["matches"] if m["match_code"] == "WOM_E1_WF_R1_M01"][0]

    # Set PAUSED
    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "PAUSED"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "PAUSED"

    # Set DELAYED
    resp2 = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/status",
        json={"version_id": draft_id, "status": "DELAYED"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "DELAYED"


# ── Court State tests ──────────────────────────────────────────────────

def test_court_state_upsert_and_get(client, session):
    """Patching court state creates row, subsequent GET returns it."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    # Patch court "1" to closed
    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/courts/1/state",
        json={"is_closed": True, "note": "Wet court"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_closed"] is True
    assert body["note"] == "Wet court"
    assert body["court_label"] == "1"

    # GET all court states
    resp2 = client.get(f"/api/desk/tournaments/{t.id}/courts/state")
    assert resp2.status_code == 200
    states = resp2.json()
    assert len(states) >= 1
    court1 = [s for s in states if s["court_label"] == "1"][0]
    assert court1["is_closed"] is True
    assert court1["note"] == "Wet court"


def test_court_state_update_preserves_fields(client, session):
    """Updating only note preserves is_closed, and vice versa."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    client.patch(
        f"/api/desk/tournaments/{t.id}/courts/1/state",
        json={"is_closed": True, "note": "Rain"},
    )

    # Update only note
    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/courts/1/state",
        json={"note": "Drying off"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_closed"] is True
    assert resp.json()["note"] == "Drying off"

    # Update only is_closed
    resp2 = client.patch(
        f"/api/desk/tournaments/{t.id}/courts/1/state",
        json={"is_closed": False},
    )
    assert resp2.status_code == 200
    assert resp2.json()["is_closed"] is False
    assert resp2.json()["note"] == "Drying off"


def test_court_state_rejects_empty_patch(client, session):
    """Patching with no fields returns 400."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/courts/1/state",
        json={},
    )
    assert resp.status_code == 400


# ── Score parser unit tests ──────────────────────────────────────────────

def test_score_parser_simple():
    """Parse a simple one-set score like '8-4'."""
    from app.services.score_parser import parse_score

    result = parse_score({"display": "8-4"})
    assert result is not None
    assert len(result.sets) == 1
    assert result.team_a_sets_won == 1
    assert result.team_b_sets_won == 0
    assert result.team_a_games == 8
    assert result.team_b_games == 4


def test_score_parser_three_sets():
    """Parse a three-set score like '6-3 4-6 10-7'."""
    from app.services.score_parser import parse_score

    result = parse_score({"display": "6-3 4-6 10-7"})
    assert result is not None
    assert len(result.sets) == 3
    assert result.team_a_sets_won == 2
    assert result.team_b_sets_won == 1
    assert result.team_a_games == 20  # 6+4+10
    assert result.team_b_games == 16  # 3+6+7


def test_score_parser_none():
    """Parsing None returns None."""
    from app.services.score_parser import parse_score

    assert parse_score(None) is None
    assert parse_score({}) is None
    assert parse_score({"display": ""}) is None


# ── Standings endpoint tests ─────────────────────────────────────────────

def _setup_rr_tournament(session: Session):
    """Create a tournament with an RR event, 4 teams, and 3 RR matches."""
    t = Tournament(
        name="RR Test",
        location="Test Beach",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(
        tournament_id=t.id,
        version_number=1,
        status="final",
    )
    session.add(v)
    session.flush()

    ev = Event(
        tournament_id=t.id,
        category="womens",
        name="Women's A",
        team_count=4,
    )
    session.add(ev)
    session.flush()

    team1 = Team(event_id=ev.id, name="Alpha - VA", seed=1, display_name="Alpha")
    team2 = Team(event_id=ev.id, name="Bravo - NC", seed=2, display_name="Bravo")
    team3 = Team(event_id=ev.id, name="Charlie - FL", seed=3, display_name="Charlie")
    session.add_all([team1, team2, team3])
    session.flush()

    # RR Match 1: Alpha vs Bravo (in POOLA)
    m1 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_E1_RR_POOLA_M01",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=team1.id,
        team_b_id=team2.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 2",
    )
    # RR Match 2: Alpha vs Charlie (in POOLA)
    m2 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_E1_RR_POOLA_M02",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        team_a_id=team1.id,
        team_b_id=team3.id,
        placeholder_side_a="Seed 1",
        placeholder_side_b="Seed 3",
    )
    # RR Match 3: Bravo vs Charlie (in POOLA)
    m3 = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WOM_E1_RR_POOLA_M03",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=3,
        duration_minutes=60,
        team_a_id=team2.id,
        team_b_id=team3.id,
        placeholder_side_a="Seed 2",
        placeholder_side_b="Seed 3",
    )
    session.add_all([m1, m2, m3])
    session.flush()

    # Create slots + assignments
    for i, m in enumerate([m1, m2, m3]):
        slot = ScheduleSlot(
            tournament_id=t.id,
            schedule_version_id=v.id,
            day_date=date(2026, 6, 5),
            start_time=time(9 + i, 0),
            end_time=time(10 + i, 0),
            court_number=1,
            court_label="1",
            block_minutes=60,
        )
        session.add(slot)
        session.flush()
        session.add(MatchAssignment(schedule_version_id=v.id, match_id=m.id, slot_id=slot.id))

    t.public_schedule_version_id = v.id
    session.add(t)
    session.commit()

    return t, v, ev, [team1, team2, team3], [m1, m2, m3]


def test_standings_no_rr_matches(client, session):
    """No RR matches returns empty events list."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)

    resp = client.get(f"/api/desk/tournaments/{t.id}/standings?version_id={v.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["events"] == []


def test_standings_with_finalized_rr(client, session):
    """Finalized RR matches produce correct standings."""
    t, v, ev, teams, matches = _setup_rr_tournament(session)

    # Create draft
    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    rr_matches = [m for m in snap["matches"] if m["stage"] == "RR"]
    assert len(rr_matches) == 3

    # Finalize M1: Alpha beats Bravo 8-4
    m1 = rr_matches[0]
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": m1["team1_id"]},
    )

    # Finalize M2: Alpha beats Charlie 6-3 6-2
    m2 = rr_matches[1]
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m2['match_id']}/finalize",
        json={"version_id": draft_id, "score": "6-3 6-2", "winner_team_id": m2["team1_id"]},
    )

    resp = client.get(f"/api/desk/tournaments/{t.id}/standings?version_id={draft_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["events"]) >= 1

    ev_standings = body["events"][0]
    rows = ev_standings["rows"]
    assert len(rows) == 3  # all 3 teams

    # Alpha should be first with 2 wins
    assert rows[0]["team_display"] == "Alpha"
    assert rows[0]["wins"] == 2
    assert rows[0]["losses"] == 0
    assert rows[0]["played"] == 2

    # Bravo and Charlie each have 0 wins, 1 loss
    non_alpha = [r for r in rows if r["team_display"] != "Alpha"]
    for r in non_alpha:
        assert r["wins"] == 0
        assert r["losses"] == 1


def test_standings_sorting_by_set_diff(client, session):
    """When wins are tied, set diff determines order."""
    t, v, ev, teams, matches = _setup_rr_tournament(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    rr_matches = sorted([m for m in snap["matches"] if m["stage"] == "RR"], key=lambda m: m["match_id"])

    # M1: Alpha beats Bravo 6-1 6-1 (dominant win)
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{rr_matches[0]['match_id']}/finalize",
        json={"version_id": draft_id, "score": "6-1 6-1", "winner_team_id": rr_matches[0]["team1_id"]},
    )

    # M2: Charlie beats Alpha 4-6 4-6 (team_a=Alpha loses, team_b=Charlie wins)
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{rr_matches[1]['match_id']}/finalize",
        json={"version_id": draft_id, "score": "4-6 4-6", "winner_team_id": rr_matches[1]["team2_id"]},
    )

    # M3: Bravo beats Charlie 6-5 6-5
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{rr_matches[2]['match_id']}/finalize",
        json={"version_id": draft_id, "score": "6-5 6-5", "winner_team_id": rr_matches[2]["team1_id"]},
    )

    resp = client.get(f"/api/desk/tournaments/{t.id}/standings?version_id={draft_id}")
    body = resp.json()
    rows = body["events"][0]["rows"]

    # All 3 teams have 1 win, 1 loss — sort by set diff (all 0 from 2 sets each),
    # then game diff
    # Alpha: won 12-2 (games +10), lost 8-12 (games -4) => total games: 20W, 14L => diff +6
    # Bravo: lost 2-12 (games -10), won 12-10 (games +2) => total games: 14W, 22L => diff -8
    # Charlie: won 12-8 (games +4), lost 10-12 (games -2) => total games: 22W, 20L => diff +2
    assert rows[0]["wins"] == 1
    assert rows[1]["wins"] == 1
    assert rows[2]["wins"] == 1
    # Alpha should be first (game diff +6), Charlie second (+2), Bravo last (-8)
    assert rows[0]["team_display"] == "Alpha"
    assert rows[1]["team_display"] == "Charlie"
    assert rows[2]["team_display"] == "Bravo"


# ── Pool Projection + Placement tests ────────────────────────────────────

def _setup_wf_pool_tournament(session: Session):
    """Create a tournament with WF_TO_POOLS_DYNAMIC (8 teams, 1 WF round, 2 pools of 4)."""
    import json

    t = Tournament(
        name="WF Pool Test",
        location="Test Beach",
        timezone="America/New_York",
        start_date=date(2026, 6, 5),
        end_date=date(2026, 6, 7),
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(
        tournament_id=t.id,
        version_number=1,
        status="final",
    )
    session.add(v)
    session.flush()

    ev = Event(
        tournament_id=t.id,
        category="mixed",
        name="Mixed A",
        team_count=8,
        draw_plan_json=json.dumps({"template_type": "WF_TO_POOLS_DYNAMIC", "wf_rounds": 1}),
    )
    session.add(ev)
    session.flush()

    # 8 teams
    teams = []
    for i in range(1, 9):
        t_obj = Team(event_id=ev.id, name=f"Team{i} - ST", seed=i, display_name=f"Team{i}")
        session.add(t_obj)
        teams.append(t_obj)
    session.flush()

    # 4 WF R1 matches: 1v5, 2v6, 3v7, 4v8 (half-split)
    wf_matches = []
    pairings = [(0, 4), (1, 5), (2, 6), (3, 7)]
    for idx, (a, b) in enumerate(pairings):
        m = Match(
            tournament_id=t.id,
            event_id=ev.id,
            schedule_version_id=v.id,
            match_code=f"MIX_E1_WF_R1_{idx+1:02d}",
            match_type="WF",
            round_number=1,
            round_index=1,
            sequence_in_round=idx + 1,
            duration_minutes=60,
            team_a_id=teams[a].id,
            team_b_id=teams[b].id,
            placeholder_side_a=f"Seed {a+1}",
            placeholder_side_b=f"Seed {b+1}",
        )
        session.add(m)
        wf_matches.append(m)
    session.flush()

    # 6 RR matches per pool (2 pools of 4, C(4,2)=6 each)
    # Pool A: SEED_1..4, Pool B: SEED_5..8
    rr_matches = []
    pool_pairings = [(1, 2), (3, 4), (1, 3), (2, 4), (1, 4), (2, 3)]
    for pool_idx in range(2):
        pool_label = chr(ord('A') + pool_idx)
        for rr_idx, (pa, pb) in enumerate(pool_pairings):
            seed_a = pool_idx * 4 + pa
            seed_b = pool_idx * 4 + pb
            m = Match(
                tournament_id=t.id,
                event_id=ev.id,
                schedule_version_id=v.id,
                match_code=f"MIX_E1_POOL{pool_label}_RR_{rr_idx+1:02d}",
                match_type="RR",
                round_number=1,
                round_index=1,
                sequence_in_round=rr_idx + 1,
                duration_minutes=120,
                team_a_id=None,
                team_b_id=None,
                placeholder_side_a=f"SEED_{seed_a}",
                placeholder_side_b=f"SEED_{seed_b}",
            )
            session.add(m)
            rr_matches.append(m)
    session.flush()

    # Create slots + assignments for WF matches
    for i, m in enumerate(wf_matches):
        slot = ScheduleSlot(
            tournament_id=t.id,
            schedule_version_id=v.id,
            day_date=date(2026, 6, 5),
            start_time=time(9 + i, 0),
            end_time=time(10 + i, 0),
            court_number=i + 1,
            court_label=str(i + 1),
            block_minutes=60,
        )
        session.add(slot)
        session.flush()
        session.add(MatchAssignment(schedule_version_id=v.id, match_id=m.id, slot_id=slot.id))

    t.public_schedule_version_id = v.id
    session.add(t)
    session.commit()

    return t, v, ev, teams, wf_matches, rr_matches


def test_pool_projection_no_wf_finalized(client, session):
    """All teams pending when no WF matches finalized."""
    t, v, ev, teams, wf_matches, rr_matches = _setup_wf_pool_tournament(session)

    resp = client.get(f"/api/desk/tournaments/{t.id}/pool-projection?version_id={v.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["events"]) == 1

    proj = body["events"][0]
    assert proj["wf_complete"] is False
    assert proj["finalized_wf_matches"] == 0
    assert proj["total_wf_matches"] == 4

    # All teams should be pending
    all_teams_in_pools = []
    for pool in proj["pools"]:
        for team in pool["teams"]:
            all_teams_in_pools.append(team)
    assert all(t["status"] == "pending" for t in all_teams_in_pools)


def test_pool_projection_partial_wf(client, session):
    """Partial WF results show mix of projected and pending."""
    t, v, ev, teams, wf_matches, rr_matches = _setup_wf_pool_tournament(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    wf = [m for m in snap["matches"] if m["stage"] == "WF"]
    wf.sort(key=lambda m: m["match_id"])

    # Finalize only first 2 WF matches
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{wf[0]['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-2", "winner_team_id": wf[0]["team1_id"]},
    )
    client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{wf[1]['match_id']}/finalize",
        json={"version_id": draft_id, "score": "8-4", "winner_team_id": wf[1]["team1_id"]},
    )

    resp = client.get(f"/api/desk/tournaments/{t.id}/pool-projection?version_id={draft_id}")
    assert resp.status_code == 200
    proj = resp.json()["events"][0]
    assert proj["wf_complete"] is False
    assert proj["finalized_wf_matches"] == 2

    # Should have a mix of projected and pending
    statuses = set()
    for pool in proj["pools"]:
        for team in pool["teams"]:
            statuses.add(team["status"])
    assert "projected" in statuses or "pending" in statuses


def test_pool_projection_all_wf_complete(client, session):
    """All WF done returns confirmed with correct pool assignments."""
    t, v, ev, teams, wf_matches, rr_matches = _setup_wf_pool_tournament(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    wf = sorted([m for m in snap["matches"] if m["stage"] == "WF"], key=lambda m: m["match_id"])

    # Finalize all 4 WF matches (team1 = higher seed wins each)
    for m in wf:
        client.patch(
            f"/api/desk/tournaments/{t.id}/matches/{m['match_id']}/finalize",
            json={"version_id": draft_id, "score": "8-3", "winner_team_id": m["team1_id"]},
        )

    resp = client.get(f"/api/desk/tournaments/{t.id}/pool-projection?version_id={draft_id}")
    assert resp.status_code == 200
    proj = resp.json()["events"][0]
    assert proj["wf_complete"] is True
    assert proj["finalized_wf_matches"] == 4

    # All teams should be confirmed
    for pool in proj["pools"]:
        for team in pool["teams"]:
            assert team["status"] == "confirmed"

    # Winners (bucket W) should be in first pool, losers (bucket L) in second
    pool_a = proj["pools"][0]
    pool_b = proj["pools"][1]
    for team in pool_a["teams"]:
        assert team["bucket"] == "W"
    for team in pool_b["teams"]:
        assert team["bucket"] == "L"


def test_pool_placement_rejects_incomplete_wf(client, session):
    """Placement fails if WF is not complete."""
    t, v, ev, teams, wf_matches, rr_matches = _setup_wf_pool_tournament(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/pool-placement",
        json={
            "version_id": draft_id,
            "event_id": ev.id,
            "pools": [
                {"pool_label": "POOLA", "team_ids": [teams[0].id, teams[1].id, teams[2].id, teams[3].id]},
                {"pool_label": "POOLB", "team_ids": [teams[4].id, teams[5].id, teams[6].id, teams[7].id]},
            ],
        },
    )
    assert resp.status_code == 400
    assert "WF not complete" in resp.json()["detail"]


def test_pool_placement_resolves_seeds(client, session):
    """After all WF complete, placement resolves SEED_N on RR matches."""
    t, v, ev, teams, wf_matches, rr_matches = _setup_wf_pool_tournament(session)

    draft_resp = client.post(f"/api/desk/tournaments/{t.id}/working-draft")
    draft_id = draft_resp.json()["version_id"]

    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    wf = sorted([m for m in snap["matches"] if m["stage"] == "WF"], key=lambda m: m["match_id"])

    # Finalize all WF: higher seed wins
    for m in wf:
        client.patch(
            f"/api/desk/tournaments/{t.id}/matches/{m['match_id']}/finalize",
            json={"version_id": draft_id, "score": "8-3", "winner_team_id": m["team1_id"]},
        )

    # Get projection to know pool assignments
    proj_resp = client.get(f"/api/desk/tournaments/{t.id}/pool-projection?version_id={draft_id}")
    proj = proj_resp.json()["events"][0]

    # Build placement payload from projection
    placement_pools = []
    for pool in proj["pools"]:
        placement_pools.append({
            "pool_label": pool["pool_label"],
            "team_ids": [t["team_id"] for t in pool["teams"]],
        })

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/pool-placement",
        json={
            "version_id": draft_id,
            "event_id": ev.id,
            "pools": placement_pools,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["updated_matches"] > 0

    # Verify RR matches now have team assignments
    rr_in_snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={draft_id}").json()
    rr_matches_after = [m for m in rr_in_snap["matches"] if m["stage"] == "RR"]
    for m in rr_matches_after:
        assert m["team1_id"] is not None, f"RR match {m['match_code']} team1_id still null"
        assert m["team2_id"] is not None, f"RR match {m['match_code']} team2_id still null"


# ── Move / Swap / Add Slot / Add Court tests ─────────────────────────────

def _setup_draft_for_move(session: Session):
    """Create a draft version with 2 courts, 2 time slots, and 2 matches."""
    t = Tournament(
        name="Move Test",
        location="Beach",
        timezone="America/New_York",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        court_names=["1", "2"],
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(
        tournament_id=t.id,
        version_number=1,
        status="draft",
        notes="Desk Draft",
    )
    session.add(v)
    session.flush()

    ev = Event(
        tournament_id=t.id,
        category="mixed",
        name="Mixed A",
        team_count=4,
    )
    session.add(ev)
    session.flush()

    teams = []
    for i, name in enumerate(["Alpha", "Bravo", "Charlie", "Delta"], start=1):
        t_ = Team(event_id=ev.id, name=name, seed=i, display_name=name)
        session.add(t_)
        session.flush()
        teams.append(t_)

    m1 = Match(
        tournament_id=t.id, event_id=ev.id, schedule_version_id=v.id,
        match_code="MIX_WF_R1_M01", match_type="WF",
        round_number=1, round_index=1, sequence_in_round=1, duration_minutes=60,
        team_a_id=teams[0].id, team_b_id=teams[3].id,
        placeholder_side_a="SEED_1", placeholder_side_b="SEED_4",
    )
    m2 = Match(
        tournament_id=t.id, event_id=ev.id, schedule_version_id=v.id,
        match_code="MIX_WF_R1_M02", match_type="WF",
        round_number=1, round_index=1, sequence_in_round=2, duration_minutes=60,
        team_a_id=teams[1].id, team_b_id=teams[2].id,
        placeholder_side_a="SEED_2", placeholder_side_b="SEED_3",
    )
    session.add_all([m1, m2])
    session.flush()

    # 2 courts x 2 time slots = 4 slots total
    slot_c1_t1 = ScheduleSlot(
        tournament_id=t.id, schedule_version_id=v.id,
        day_date=date(2026, 7, 1), start_time=time(9, 0), end_time=time(10, 0),
        court_number=1, court_label="1", block_minutes=60,
    )
    slot_c2_t1 = ScheduleSlot(
        tournament_id=t.id, schedule_version_id=v.id,
        day_date=date(2026, 7, 1), start_time=time(9, 0), end_time=time(10, 0),
        court_number=2, court_label="2", block_minutes=60,
    )
    slot_c1_t2 = ScheduleSlot(
        tournament_id=t.id, schedule_version_id=v.id,
        day_date=date(2026, 7, 1), start_time=time(10, 30), end_time=time(11, 30),
        court_number=1, court_label="1", block_minutes=60,
    )
    slot_c2_t2 = ScheduleSlot(
        tournament_id=t.id, schedule_version_id=v.id,
        day_date=date(2026, 7, 1), start_time=time(10, 30), end_time=time(11, 30),
        court_number=2, court_label="2", block_minutes=60,
    )
    session.add_all([slot_c1_t1, slot_c2_t1, slot_c1_t2, slot_c2_t2])
    session.flush()

    a1 = MatchAssignment(schedule_version_id=v.id, match_id=m1.id, slot_id=slot_c1_t1.id)
    a2 = MatchAssignment(schedule_version_id=v.id, match_id=m2.id, slot_id=slot_c2_t1.id)
    session.add_all([a1, a2])
    session.commit()

    return t, v, ev, teams, [m1, m2], [slot_c1_t1, slot_c2_t1, slot_c1_t2, slot_c2_t2]


def test_move_match_to_empty_slot(client, session):
    """Moving a match to an empty slot succeeds."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)
    m1 = matches[0]
    empty_slot = slots[2]  # slot_c1_t2 (empty)

    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/move",
        json={"version_id": v.id, "target_slot_id": empty_slot.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["match"]["match_id"] == m1.id


def test_move_match_to_occupied_slot_returns_409(client, session):
    """Moving a match to a slot occupied by another match returns 409."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)
    m1 = matches[0]
    occupied_slot = slots[1]  # slot_c2_t1 holds m2

    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/move",
        json={"version_id": v.id, "target_slot_id": occupied_slot.id},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["occupant_match_id"] == matches[1].id


def test_move_rejected_on_final_version(client, session):
    """Move is rejected on a FINAL version."""
    t, v, ev, teams, matches = _setup_tournament_with_matches(session)
    m1 = matches[0]

    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/move",
        json={"version_id": v.id, "target_slot_id": 999},
    )
    assert resp.status_code == 400
    assert "DRAFT" in resp.json()["detail"]


def test_swap_two_matches(client, session):
    """Swapping two matches exchanges their slot assignments."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)
    m1, m2 = matches

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/matches/swap",
        json={"version_id": v.id, "match_a_id": m1.id, "match_b_id": m2.id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True

    # Verify assignments are swapped
    a1 = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == v.id,
            MatchAssignment.match_id == m1.id,
        )
    ).first()
    a2 = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == v.id,
            MatchAssignment.match_id == m2.id,
        )
    ).first()
    assert a1.slot_id == slots[1].id  # m1 now on court 2
    assert a2.slot_id == slots[0].id  # m2 now on court 1


def test_add_time_slot(client, session):
    """Adding a time slot creates new ScheduleSlot records."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/slots",
        json={
            "version_id": v.id,
            "day_date": "2026-07-01",
            "start_time": "14:00",
            "end_time": "15:00",
            "court_numbers": [1, 2],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert len(body["created_slots"]) == 2
    assert body["created_slots"][0]["start_time"] == "14:00"


def test_add_court(client, session):
    """Adding a court appends to tournament.court_names."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/courts",
        json={
            "version_id": v.id,
            "court_label": "3",
            "create_matching_slots": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "3" in body["courts"]
    assert body["created_slots"] > 0

    session.refresh(t)
    assert "3" in t.court_names


def test_conflict_check_move_day_cap(client, session):
    """Conflict check for MOVE detects day cap exceeded at target slot."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)
    m1, m2 = matches
    slot_c1_t2 = slots[2]

    # Mark m1 as IN_PROGRESS (counts toward daily cap)
    m1.runtime_status = "IN_PROGRESS"
    session.add(m1)
    # Mark m2 as FINAL (also counts)
    m2.runtime_status = "FINAL"
    m2.winner_team_id = teams[1].id
    session.add(m2)
    session.flush()

    # Create a third match for Bravo (also FINAL) to give Bravo 2 FINAL/IP matches
    m3_extra = Match(
        tournament_id=t.id, event_id=ev.id, schedule_version_id=v.id,
        match_code="MIX_WF_R1_M03", match_type="WF",
        round_number=1, round_index=1, sequence_in_round=3, duration_minutes=60,
        team_a_id=teams[1].id, team_b_id=teams[3].id,
        placeholder_side_a="SEED_2", placeholder_side_b="SEED_4",
        runtime_status="FINAL", winner_team_id=teams[1].id,
    )
    session.add(m3_extra)
    session.flush()
    slot_c2_t2 = slots[3]
    a3x = MatchAssignment(schedule_version_id=v.id, match_id=m3_extra.id, slot_id=slot_c2_t2.id)
    session.add(a3x)
    session.flush()

    # Create a fourth match for Bravo (the one we'll check)
    m4 = Match(
        tournament_id=t.id, event_id=ev.id, schedule_version_id=v.id,
        match_code="MIX_WF_R2_M01", match_type="WF",
        round_number=2, round_index=1, sequence_in_round=1, duration_minutes=60,
        team_a_id=teams[1].id, team_b_id=teams[0].id,
        placeholder_side_a="W1", placeholder_side_b="W2",
    )
    session.add(m4)
    session.flush()

    # Need a 5th slot for m4
    extra_slot = ScheduleSlot(
        tournament_id=t.id, schedule_version_id=v.id,
        day_date=date(2026, 7, 1), start_time=time(12, 0), end_time=time(13, 0),
        court_number=1, court_label="1", block_minutes=60,
    )
    session.add(extra_slot)
    session.flush()

    a4 = MatchAssignment(schedule_version_id=v.id, match_id=m4.id, slot_id=extra_slot.id)
    session.add(a4)
    session.commit()

    # Check conflicts for setting m4 IN_PROGRESS — Bravo already has 2 matches today (m2 FINAL + m3_extra FINAL)
    resp = client.post(
        f"/api/desk/tournaments/{t.id}/conflicts/check",
        json={
            "version_id": v.id,
            "action_type": "SET_IN_PROGRESS",
            "match_id": m4.id,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    day_cap_conflicts = [c for c in body["conflicts"] if c["code"] == "DAY_CAP_EXCEEDED"]
    assert len(day_cap_conflicts) > 0


def test_conflict_check_move_with_target_slot(client, session):
    """Conflict check with target_slot_id uses the target slot for evaluation."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)
    m1 = matches[0]

    # target slot is on same day, same team — should run without error
    resp = client.post(
        f"/api/desk/tournaments/{t.id}/conflicts/check",
        json={
            "version_id": v.id,
            "action_type": "MOVE",
            "match_id": m1.id,
            "target_slot_id": slots[2].id,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["conflicts"], list)


def test_snapshot_includes_slots_and_grid_fields(client, session):
    """Snapshot response includes slots array and grid fields per match."""
    t, v, ev, teams, matches, slots = _setup_draft_for_move(session)

    resp = client.get(f"/api/desk/tournaments/{t.id}/snapshot?version_id={v.id}")
    assert resp.status_code == 200
    body = resp.json()

    assert "slots" in body
    assert len(body["slots"]) == 4  # 2 courts x 2 times

    m1_data = next(m for m in body["matches"] if m["match_id"] == matches[0].id)
    assert m1_data["slot_id"] is not None
    assert m1_data["assignment_id"] is not None
    assert m1_data["court_number"] is not None
    assert m1_data["day_date"] is not None


# ── Reschedule Engine tests ──────────────────────────────────────────────

def _setup_reschedule(session: Session, *, num_matches=4):
    """
    Set up a two-day, 2-court tournament with matches assigned on Day 1.
    Returns (tournament, version, event, teams, matches, slots).
    Day 1 slots: 09:00, 10:30 on courts 1,2  (4 slots)
    Day 2 slots: 09:00, 10:30 on courts 1,2  (4 slots)
    """
    t = Tournament(
        name="Rain Test",
        location="Beach",
        timezone="America/New_York",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        court_names=["1", "2"],
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(
        tournament_id=t.id, version_number=1, status="draft", notes="Desk Draft",
    )
    session.add(v)
    session.flush()

    ev = Event(tournament_id=t.id, category="mixed", name="Mixed A", team_count=8)
    session.add(ev)
    session.flush()

    teams = []
    for i in range(1, num_matches * 2 + 1):
        team = Team(event_id=ev.id, name=f"Team{i}", seed=i, display_name=f"Team {i}")
        session.add(team)
        session.flush()
        teams.append(team)

    matches = []
    for i in range(num_matches):
        m = Match(
            tournament_id=t.id, event_id=ev.id, schedule_version_id=v.id,
            match_code=f"MIX_WF_R1_M{i+1:02d}", match_type="WF",
            round_number=1, round_index=1, sequence_in_round=i + 1, duration_minutes=60,
            team_a_id=teams[i * 2].id, team_b_id=teams[i * 2 + 1].id,
            placeholder_side_a=f"SEED_{i*2+1}", placeholder_side_b=f"SEED_{i*2+2}",
        )
        session.add(m)
        session.flush()
        matches.append(m)

    # Day 1: 4 slots
    d1_slots = []
    for ct in [1, 2]:
        for h, m in [(9, 0), (10, 30)]:
            s = ScheduleSlot(
                tournament_id=t.id, schedule_version_id=v.id,
                day_date=date(2026, 7, 1), start_time=time(h, m), end_time=time(h + 1, m),
                court_number=ct, court_label=str(ct), block_minutes=60,
            )
            session.add(s)
            session.flush()
            d1_slots.append(s)

    # Day 2: 4 slots
    d2_slots = []
    for ct in [1, 2]:
        for h, m in [(9, 0), (10, 30)]:
            s = ScheduleSlot(
                tournament_id=t.id, schedule_version_id=v.id,
                day_date=date(2026, 7, 2), start_time=time(h, m), end_time=time(h + 1, m),
                court_number=ct, court_label=str(ct), block_minutes=60,
            )
            session.add(s)
            session.flush()
            d2_slots.append(s)

    # Assign matches to Day 1 slots
    for i, m in enumerate(matches[:len(d1_slots)]):
        a = MatchAssignment(schedule_version_id=v.id, match_id=m.id, slot_id=d1_slots[i].id)
        session.add(a)

    session.commit()

    return t, v, ev, teams, matches, d1_slots + d2_slots


def test_reschedule_partial_day(client, session):
    """Partial day: matches after cutoff are moved to available slots."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "PARTIAL_DAY",
        "affected_day": "2026-07-01",
        "unavailable_from": "10:00",
        "available_from": "14:00",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    body = resp.json()

    assert body["stats"]["total_affected"] > 0
    assert body["stats"]["total_moved"] > 0
    for move in body["proposed_moves"]:
        assert move["new_slot_id"] is not None
        assert move["match_id"] in [m.id for m in matches]


def test_reschedule_full_washout(client, session):
    """Full washout: all Day 1 unplayed matches move to Day 2."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    body = resp.json()

    assert body["stats"]["total_affected"] == 4
    for move in body["proposed_moves"]:
        assert move["new_day"] == "2026-07-02"


def test_reschedule_court_loss(client, session):
    """Court loss: matches on court 2 redistributed away from affected slots."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "COURT_LOSS",
        "affected_day": "2026-07-01",
        "unavailable_courts": [2],
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    body = resp.json()

    affected = body["stats"]["total_affected"]
    assert affected > 0
    for move in body["proposed_moves"]:
        # Moved matches should not land on court 2 on the affected day
        if move["new_day"] == "2026-07-01":
            assert "Court 2" not in move["new_court"]


def test_reschedule_locked_matches_excluded(client, session):
    """Locked matches are not moved by the reschedule engine."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    # Lock the first match
    assignment = session.exec(
        select(MatchAssignment).where(
            MatchAssignment.schedule_version_id == v.id,
            MatchAssignment.match_id == matches[0].id,
        )
    ).first()
    assignment.locked = True
    session.add(assignment)
    session.commit()

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    body = resp.json()

    moved_ids = [m["match_id"] for m in body["proposed_moves"]]
    assert matches[0].id not in moved_ids


def test_reschedule_final_matches_excluded(client, session):
    """FINAL matches are not moved by the reschedule engine."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    # Mark first match as FINAL
    matches[0].runtime_status = "FINAL"
    session.add(matches[0])
    session.commit()

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    body = resp.json()

    moved_ids = [m["match_id"] for m in body["proposed_moves"]]
    assert matches[0].id not in moved_ids
    assert body["stats"]["total_kept"] >= 1


def test_reschedule_unplaceable_when_no_slots(client, session):
    """When no slots are available and add_time_slots is off, matches are unplaceable."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session, num_matches=4)

    # Mark ALL Day 2 slots as inactive so nothing is available
    for s in slots:
        if s.day_date == date(2026, 7, 2):
            s.is_active = False
            session.add(s)
    session.commit()

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    body = resp.json()

    assert body["stats"]["total_unplaceable"] > 0
    assert len(body["unplaceable"]) > 0


def test_reschedule_apply(client, session):
    """Apply reschedule updates match assignments."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    # Preview
    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    preview = resp.json()

    # Apply
    moves = [{"match_id": m["match_id"], "new_slot_id": m["new_slot_id"]} for m in preview["proposed_moves"]]
    resp2 = client.post(f"/api/desk/tournaments/{t.id}/reschedule/apply", json={
        "version_id": v.id,
        "moves": moves,
    })
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["applied_moves"] == len(moves)

    # Verify assignments are updated
    for m in preview["proposed_moves"]:
        assign = session.exec(
            select(MatchAssignment).where(
                MatchAssignment.schedule_version_id == v.id,
                MatchAssignment.match_id == m["match_id"],
            )
        ).first()
        assert assign is not None
        assert assign.slot_id == m["new_slot_id"]
        assert assign.locked is True


def test_reschedule_rejects_final_version(client, session):
    """Reschedule preview rejects non-draft versions."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    v.status = "final"
    session.add(v)
    session.commit()

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
    })
    assert resp.status_code == 400


def test_reschedule_feasibility(client, session):
    """Feasibility endpoint returns correct fits/utilization for each format."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/feasibility", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
    })
    assert resp.status_code == 200
    body = resp.json()

    assert body["affected_count"] == 4
    assert len(body["formats"]) == 3

    fmt_by_key = {f["format"]: f for f in body["formats"]}
    assert "REGULAR" in fmt_by_key
    assert "PRO_SET_8" in fmt_by_key
    assert "PRO_SET_4" in fmt_by_key

    assert fmt_by_key["REGULAR"]["duration"] == 105
    assert fmt_by_key["PRO_SET_8"]["duration"] == 60
    assert fmt_by_key["PRO_SET_4"]["duration"] == 35

    # 4 Day 2 slots x 60 min = 240 available minutes
    # Regular: 4 * 105 = 420 needed -> won't fit
    assert fmt_by_key["REGULAR"]["fits"] is False
    # Pro Set 8: 4 * 60 = 240 needed -> exactly fits
    assert fmt_by_key["PRO_SET_8"]["fits"] is True
    # Pro Set 4: 4 * 35 = 140 needed -> fits easily
    assert fmt_by_key["PRO_SET_4"]["fits"] is True

    for f in body["formats"]:
        assert isinstance(f["utilization"], int)
        assert "label" in f


def test_reschedule_preview_with_scoring_format(client, session):
    """Preview with scoring_format uses compressed durations for placement."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
        "scoring_format": "PRO_SET_4",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    body = resp.json()

    assert body["format_applied"] == "PRO_SET_4"
    assert body["duration_updates"] is not None
    assert len(body["duration_updates"]) > 0

    for match_id_str, new_dur in body["duration_updates"].items():
        assert new_dur == 35

    assert body["stats"]["total_moved"] > 0
    assert body["stats"]["total_affected"] == 4


def test_reschedule_apply_with_duration_updates(client, session):
    """Apply with duration_updates persists new match durations."""
    t, v, ev, teams, matches, slots = _setup_reschedule(session)

    # Preview with compressed format
    resp = client.post(f"/api/desk/tournaments/{t.id}/reschedule/preview", json={
        "version_id": v.id,
        "mode": "FULL_WASHOUT",
        "affected_day": "2026-07-01",
        "scoring_format": "PRO_SET_4",
        "add_time_slots": False,
    })
    assert resp.status_code == 200
    preview = resp.json()

    moves = [{"match_id": m["match_id"], "new_slot_id": m["new_slot_id"]} for m in preview["proposed_moves"]]

    # Apply with duration_updates
    resp2 = client.post(f"/api/desk/tournaments/{t.id}/reschedule/apply", json={
        "version_id": v.id,
        "moves": moves,
        "duration_updates": preview["duration_updates"],
    })
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["applied_moves"] == len(moves)

    # Verify match durations updated in DB
    for match_id_str in preview["duration_updates"]:
        match = session.get(Match, int(match_id_str))
        assert match is not None
        assert match.duration_minutes == 35
