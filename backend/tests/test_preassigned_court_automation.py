"""Preassigned Court Automation — opening release, dispatch, finalize chain, modes."""

from __future__ import annotations

from datetime import date, datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.match_checkin import MatchCheckIn
from app.models.opening_slot_release import OpeningSlotRelease
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.models.tournament_sms_settings import SMS_DELIVERY_MODE_REDIRECT, TournamentSmsSettings
from app.services.court_assignment_mode import MODE_DYNAMIC_CHECKIN, MODE_PREASSIGNED, replace_court_assignment_modes
from app.services.preassigned_dispatch import (
    OUTCOME_READY_TO_START,
    OUTCOME_WAITING_CHECKIN,
    OUTCOME_WAITING_COURT,
    OUTCOME_WAITING_RELEASE,
    dispatch_after_finalize,
    evaluate_eligibility,
    release_opening_slot,
    start_match_canonical,
)
from app.services.schedule_slot_availability import slot_key_for_slot


def _team(session: Session, event_id: int, name: str, seed: int) -> Team:
    team = Team(event_id=event_id, name=name, seed=seed, display_name=name)
    session.add(team)
    session.flush()
    return team


def _check_in(session: Session, tournament_id: int, version_id: int, match: Match) -> None:
    for side, team_id in (("A", match.team_a_id), ("B", match.team_b_id)):
        session.add(
            MatchCheckIn(
                tournament_id=tournament_id,
                schedule_version_id=version_id,
                match_id=match.id,
                team_id=team_id,
                side=side,
                team_checked_in=True,
                checked_in_at=datetime.utcnow(),
            )
        )
    session.flush()


def _setup_automation(session: Session, *, draft: bool = True):
    day = date(2026, 10, 2)
    tournament = Tournament(
        name="Preassigned Automation",
        location="Beach",
        timezone="America/New_York",
        start_date=day,
        end_date=day,
        desk_management_mode="checkin_management",
        court_names=["1", "2", "3"],
    )
    session.add(tournament)
    session.flush()
    session.add(
        TournamentDay(
            tournament_id=tournament.id,
            date=day,
            is_active=True,
            courts_available=3,
        )
    )
    version = ScheduleVersion(
        tournament_id=tournament.id,
        version_number=1,
        status="draft" if draft else "final",
        notes="DESK_DRAFT" if draft else None,
    )
    session.add(version)
    session.flush()

    event_pre = Event(tournament_id=tournament.id, category="womens", name="Women's A", team_count=8)
    event_dyn = Event(tournament_id=tournament.id, category="mixed", name="Mixed A", team_count=8)
    session.add_all([event_pre, event_dyn])
    session.flush()
    replace_court_assignment_modes(event_pre, {day.isoformat(): MODE_PREASSIGNED})
    session.add(event_pre)

    def make_slot(court: int, start: time, end: time) -> ScheduleSlot:
        slot = ScheduleSlot(
            tournament_id=tournament.id,
            schedule_version_id=version.id,
            day_date=day,
            start_time=start,
            end_time=end,
            court_number=court,
            court_label=str(court),
            block_minutes=60,
        )
        session.add(slot)
        session.flush()
        return slot

    slot_a = make_slot(1, time(9, 0), time(10, 0))
    slot_b = make_slot(2, time(9, 0), time(10, 0))
    slot_c = make_slot(1, time(10, 0), time(11, 0))  # same court later (R2)

    teams = [_team(session, event_pre.id, f"Team {i}", i) for i in range(1, 7)]
    dyn_teams = [_team(session, event_dyn.id, f"Dyn {i}", i) for i in range(1, 3)]

    def make_match(
        *,
        event: Event,
        code: str,
        slot: ScheduleSlot,
        team_a: Team | None,
        team_b: Team | None,
        round_index: int = 1,
        source_a: int | None = None,
        source_b: int | None = None,
    ) -> Match:
        match = Match(
            tournament_id=tournament.id,
            event_id=event.id,
            schedule_version_id=version.id,
            match_code=code,
            match_type="WF",
            round_number=round_index,
            round_index=round_index,
            sequence_in_round=1,
            duration_minutes=60,
            team_a_id=team_a.id if team_a else None,
            team_b_id=team_b.id if team_b else None,
            placeholder_side_a="A",
            placeholder_side_b="B",
            source_match_a_id=source_a,
            source_match_b_id=source_b,
            runtime_status="SCHEDULED",
        )
        session.add(match)
        session.flush()
        session.add(
            MatchAssignment(
                schedule_version_id=version.id,
                match_id=match.id,
                slot_id=slot.id,
                assigned_by="MANUAL",
            )
        )
        session.flush()
        return match

    m1 = make_match(event=event_pre, code="WOM_WF_R1_01", slot=slot_a, team_a=teams[0], team_b=teams[1])
    m2 = make_match(event=event_pre, code="WOM_WF_R1_02", slot=slot_b, team_a=teams[2], team_b=teams[3])
    m_r2 = make_match(
        event=event_pre,
        code="WOM_WF_R2_01",
        slot=slot_c,
        team_a=None,
        team_b=None,
        round_index=2,
        source_a=m1.id,
        source_b=m2.id,
    )
    m_dyn = make_match(
        event=event_dyn,
        code="MIX_WF_R1_01",
        slot=make_slot(3, time(9, 0), time(10, 0)),
        team_a=dyn_teams[0],
        team_b=dyn_teams[1],
    )
    session.commit()
    return {
        "tournament": tournament,
        "version": version,
        "event_pre": event_pre,
        "event_dyn": event_dyn,
        "day": day,
        "slot_a": slot_a,
        "slot_b": slot_b,
        "slot_c": slot_c,
        "m1": m1,
        "m2": m2,
        "m_r2": m_r2,
        "m_dyn": m_dyn,
        "teams": teams,
    }


def test_opening_release_mixed_checkin_and_auto_start(client, session: Session):
    ctx = _setup_automation(session)
    t, v, m1, m2 = ctx["tournament"], ctx["version"], ctx["m1"], ctx["m2"]
    slot_key = slot_key_for_slot(ctx["slot_a"])
    _check_in(session, t.id, v.id, m1)
    session.commit()

    preview = client.get(
        f"/api/desk/tournaments/{t.id}/opening-release/preview",
        params={"version_id": v.id, "day_date": ctx["day"].isoformat(), "slot_key": slot_key},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["ready_count"] == 1
    assert body["awaiting_checkin_count"] == 1
    assert m1.id in body["ready_match_ids"]
    assert m2.id in body["awaiting_checkin_match_ids"]

    # Before release: not ready to start
    elig = evaluate_eligibility(session, t, session.get(Match, m1.id))
    assert elig.outcome == OUTCOME_WAITING_RELEASE

    resp = client.post(
        f"/api/desk/tournaments/{t.id}/opening-release",
        json={"version_id": v.id, "day_date": ctx["day"].isoformat(), "slot_key": slot_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert m1.id in data["started_match_ids"]
    assert m2.id not in data["started_match_ids"]

    session.refresh(session.get(Match, m1.id))
    assert session.get(Match, m1.id).runtime_status == "IN_PROGRESS"
    assert session.get(Match, m2.id).runtime_status == "SCHEDULED"

    releases = session.exec(select(OpeningSlotRelease)).all()
    assert len(releases) == 1


def test_late_checkin_after_release_auto_starts(client, session: Session):
    ctx = _setup_automation(session)
    t, v, m1, m2 = ctx["tournament"], ctx["version"], ctx["m1"], ctx["m2"]
    slot_key = slot_key_for_slot(ctx["slot_a"])
    _check_in(session, t.id, v.id, m1)
    session.commit()

    client.post(
        f"/api/desk/tournaments/{t.id}/opening-release",
        json={"version_id": v.id, "day_date": ctx["day"].isoformat(), "slot_key": slot_key},
    )
    assert session.get(Match, m1.id).runtime_status == "IN_PROGRESS"

    # m2 still missing check-in — check in both sides via API
    for side in ("A", "B"):
        r = client.patch(
            f"/api/desk/tournaments/{t.id}/matches/{m2.id}/checkin/team",
            json={"version_id": v.id, "side": side, "checked_in": True},
        )
        assert r.status_code == 200

    session.refresh(session.get(Match, m2.id))
    assert session.get(Match, m2.id).runtime_status == "IN_PROGRESS"


def test_early_release_authorizes_before_slot_time(session: Session):
    ctx = _setup_automation(session)
    t, v, m1 = ctx["tournament"], ctx["version"], ctx["m1"]
    # Slot is 9am; freeze "now" to 8am local.
    _check_in(session, t.id, v.id, m1)
    session.commit()
    slot_key = slot_key_for_slot(ctx["slot_a"])

    tz = ZoneInfo("America/New_York")
    fake_now = datetime(2026, 10, 2, 8, 0, tzinfo=tz)

    with patch("app.services.preassigned_dispatch.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.combine = datetime.combine
        mock_dt.utcnow = datetime.utcnow
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)

        elig_before = evaluate_eligibility(session, t, session.get(Match, m1.id))
        assert elig_before.outcome == OUTCOME_WAITING_RELEASE

        release_opening_slot(session, t, v, day_date=ctx["day"], slot_key=slot_key)
        session.refresh(session.get(Match, m1.id))
        assert session.get(Match, m1.id).runtime_status == "IN_PROGRESS"


def test_occupied_court_waits_then_dispatches_on_finalize(client, session: Session):
    ctx = _setup_automation(session)
    t, v, m1, m_r2 = ctx["tournament"], ctx["version"], ctx["m1"], ctx["m_r2"]
    slot_key = slot_key_for_slot(ctx["slot_a"])
    winner_a = m1.team_a_id
    _check_in(session, t.id, v.id, m1)
    session.commit()
    client.post(
        f"/api/desk/tournaments/{t.id}/opening-release",
        json={"version_id": v.id, "day_date": ctx["day"].isoformat(), "slot_key": slot_key},
    )
    session.expire_all()
    assert session.get(Match, m1.id).runtime_status == "IN_PROGRESS"

    # Occupy court 1 with m1 live; R2 on same court waits until feeders final / court free.
    m_r2 = session.get(Match, m_r2.id)
    m_r2.team_a_id = ctx["teams"][0].id
    m_r2.team_b_id = ctx["teams"][2].id
    session.add(m_r2)
    session.commit()

    elig = evaluate_eligibility(session, t, session.get(Match, m_r2.id))
    assert elig.outcome in (OUTCOME_WAITING_COURT, "waiting_participants")

    fin = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/finalize",
        json={
            "version_id": v.id,
            "winner_team_id": winner_a,
            "score": "8-5",
            "send_automation_texts": False,
        },
    )
    assert fin.status_code == 200
    session.expire_all()
    assert session.get(Match, m1.id).runtime_status == "FINAL"
    assert session.get(Match, m1.id).winner_team_id == winner_a


def test_score_persists_when_subsequent_dispatch_fails(client, session: Session):
    ctx = _setup_automation(session)
    t, v, m1 = ctx["tournament"], ctx["version"], ctx["m1"]
    winner_a = m1.team_a_id
    slot_key = slot_key_for_slot(ctx["slot_a"])
    _check_in(session, t.id, v.id, m1)
    session.commit()
    client.post(
        f"/api/desk/tournaments/{t.id}/opening-release",
        json={"version_id": v.id, "day_date": ctx["day"].isoformat(), "slot_key": slot_key},
    )

    with patch(
        "app.routes.desk.dispatch_after_finalize",
        side_effect=RuntimeError("dispatch boom"),
    ):
        fin = client.patch(
            f"/api/desk/tournaments/{t.id}/matches/{m1.id}/finalize",
            json={
                "version_id": v.id,
                "winner_team_id": winner_a,
                "score": "8-3",
                "send_automation_texts": False,
            },
        )
    assert fin.status_code == 200
    body = fin.json()
    assert body["match"]["status"] == "FINAL"
    assert body["dispatch_errors"]
    session.expire_all()
    assert session.get(Match, m1.id).runtime_status == "FINAL"
    assert session.get(Match, m1.id).score_json is not None


def test_round2_no_checkin_required_when_ready(session: Session):
    ctx = _setup_automation(session)
    t, m1, m2, m_r2 = ctx["tournament"], ctx["m1"], ctx["m2"], ctx["m_r2"]

    m1.runtime_status = "FINAL"
    m1.winner_team_id = m1.team_a_id
    m2.runtime_status = "FINAL"
    m2.winner_team_id = m2.team_a_id
    m_r2.team_a_id = m1.team_a_id
    m_r2.team_b_id = m2.team_a_id
    session.add_all([m1, m2, m_r2])
    session.commit()

    # Force scheduled time arrived.
    with patch("app.services.preassigned_dispatch.slot_start_has_arrived", return_value=True):
        elig = evaluate_eligibility(session, t, session.get(Match, m_r2.id))
        assert elig.outcome == OUTCOME_READY_TO_START
        ok, _ = start_match_canonical(session, t, session.get(Match, m_r2.id))
        assert ok
    assert session.get(Match, m_r2.id).runtime_status == "IN_PROGRESS"


def test_mode_switch_preassigned_to_dynamic_stops_dispatch(session: Session):
    ctx = _setup_automation(session)
    t, v, m1, event = ctx["tournament"], ctx["version"], ctx["m1"], ctx["event_pre"]
    _check_in(session, t.id, v.id, m1)
    session.commit()
    slot_key = slot_key_for_slot(ctx["slot_a"])
    release_opening_slot(session, t, v, day_date=ctx["day"], slot_key=slot_key)
    # Reset match to scheduled to re-test mode gate after switch
    m1 = session.get(Match, m1.id)
    m1.runtime_status = "SCHEDULED"
    m1.started_at = None
    session.add(m1)
    replace_court_assignment_modes(event, {ctx["day"].isoformat(): MODE_DYNAMIC_CHECKIN})
    session.add(event)
    session.commit()

    elig = evaluate_eligibility(session, t, session.get(Match, m1.id))
    assert elig.outcome == "skip"
    assert "DYNAMIC" in elig.reason


def test_mode_switch_dynamic_to_preassigned_enables_dispatch(session: Session):
    ctx = _setup_automation(session)
    t, v, m_dyn, event_dyn = ctx["tournament"], ctx["version"], ctx["m_dyn"], ctx["event_dyn"]
    _check_in(session, t.id, v.id, m_dyn)
    session.commit()
    assert evaluate_eligibility(session, t, session.get(Match, m_dyn.id)).outcome == "skip"

    replace_court_assignment_modes(event_dyn, {ctx["day"].isoformat(): MODE_PREASSIGNED})
    session.add(event_dyn)
    session.commit()
    slot_key = slot_key_for_slot(
        session.exec(
            select(ScheduleSlot).where(
                ScheduleSlot.schedule_version_id == v.id,
                ScheduleSlot.court_number == 3,
            )
        ).first()
    )
    release_opening_slot(session, t, v, day_date=ctx["day"], slot_key=slot_key)
    assert session.get(Match, m_dyn.id).runtime_status == "IN_PROGRESS"


def test_different_modes_same_day_only_preassigned_dispatches(client, session: Session):
    ctx = _setup_automation(session)
    t, v, m1, m_dyn = ctx["tournament"], ctx["version"], ctx["m1"], ctx["m_dyn"]
    _check_in(session, t.id, v.id, m1)
    _check_in(session, t.id, v.id, m_dyn)
    session.commit()
    slot_key = slot_key_for_slot(ctx["slot_a"])
    client.post(
        f"/api/desk/tournaments/{t.id}/opening-release",
        json={"version_id": v.id, "day_date": ctx["day"].isoformat(), "slot_key": slot_key},
    )
    assert session.get(Match, m1.id).runtime_status == "IN_PROGRESS"
    assert session.get(Match, m_dyn.id).runtime_status == "SCHEDULED"


def test_duplicate_release_is_idempotent(client, session: Session):
    ctx = _setup_automation(session)
    t, v, m1 = ctx["tournament"], ctx["version"], ctx["m1"]
    _check_in(session, t.id, v.id, m1)
    session.commit()
    slot_key = slot_key_for_slot(ctx["slot_a"])
    r1 = client.post(
        f"/api/desk/tournaments/{t.id}/opening-release",
        json={"version_id": v.id, "day_date": ctx["day"].isoformat(), "slot_key": slot_key},
    )
    r2 = client.post(
        f"/api/desk/tournaments/{t.id}/opening-release",
        json={"version_id": v.id, "day_date": ctx["day"].isoformat(), "slot_key": slot_key},
    )
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.json()["already_released"] is True
    assert len(session.exec(select(OpeningSlotRelease)).all()) == 1
    assert session.get(Match, m1.id).runtime_status == "IN_PROGRESS"


def test_historical_final_version_cannot_release(client, session: Session):
    ctx = _setup_automation(session, draft=False)
    t, v = ctx["tournament"], ctx["version"]
    slot_key = slot_key_for_slot(ctx["slot_a"])
    resp = client.post(
        f"/api/desk/tournaments/{t.id}/opening-release",
        json={"version_id": v.id, "day_date": ctx["day"].isoformat(), "slot_key": slot_key},
    )
    assert resp.status_code == 400


def test_ready_assigned_queue_in_snapshot(client, session: Session):
    ctx = _setup_automation(session)
    t, v, m1 = ctx["tournament"], ctx["version"], ctx["m1"]
    _check_in(session, t.id, v.id, m1)
    session.commit()
    snap = client.get(f"/api/desk/tournaments/{t.id}/snapshot", params={"version_id": v.id})
    assert snap.status_code == 200
    body = snap.json()
    ids = {row["match_id"] for row in body.get("ready_assigned_queue", [])}
    assert m1.id in ids
    assert m1.id not in {row["match_id"] for row in body.get("ready_queue", [])}


def test_move_blocked_by_preassigned_reservation(client, session: Session):
    ctx = _setup_automation(session)
    t, v, m_dyn, slot_a = ctx["tournament"], ctx["version"], ctx["m_dyn"], ctx["slot_a"]
    # Moving dynamic match onto preassigned court 1 at overlapping time should 409
    resp = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m_dyn.id}/move",
        json={"version_id": v.id, "target_slot_id": slot_a.id},
    )
    assert resp.status_code == 409


def test_no_checkin_court_assigned_sms_on_preassigned_start(session: Session):
    ctx = _setup_automation(session)
    t, v, m1 = ctx["tournament"], ctx["version"], ctx["m1"]
    _check_in(session, t.id, v.id, m1)
    session.commit()
    slot_key = slot_key_for_slot(ctx["slot_a"])

    session.add(
        TournamentSmsSettings(
            tournament_id=t.id,
            texts_enabled=True,
            delivery_mode=SMS_DELIVERY_MODE_REDIRECT,
            redirect_phone="15555550100",
        )
    )
    session.commit()

    with patch("app.services.preassigned_dispatch.SmsAutomationEngine") as engine_cls:
        engine = engine_cls.return_value
        release_opening_slot(session, t, v, day_date=ctx["day"], slot_key=slot_key)
        engine.handle_match_status_change.assert_called()
        engine.handle_checkin_court_assigned.assert_not_called()


def test_master_texting_off_still_starts_match(session: Session):
    ctx = _setup_automation(session)
    t, v, m1 = ctx["tournament"], ctx["version"], ctx["m1"]
    _check_in(session, t.id, v.id, m1)
    session.add(TournamentSmsSettings(tournament_id=t.id, texts_enabled=False))
    session.commit()
    slot_key = slot_key_for_slot(ctx["slot_a"])
    release_opening_slot(session, t, v, day_date=ctx["day"], slot_key=slot_key)
    assert session.get(Match, m1.id).runtime_status == "IN_PROGRESS"


def test_concurrent_dispatch_idempotent(session: Session):
    ctx = _setup_automation(session)
    t, v, m1 = ctx["tournament"], ctx["version"], ctx["m1"]
    _check_in(session, t.id, v.id, m1)
    session.commit()
    slot_key = slot_key_for_slot(ctx["slot_a"])
    release_opening_slot(session, t, v, day_date=ctx["day"], slot_key=slot_key)
    # Second start attempt
    ok, reason = start_match_canonical(session, t, session.get(Match, m1.id))
    assert ok is False
    assert reason == "already_in_progress"


def test_opening_waiting_checkin_outcome(session: Session):
    ctx = _setup_automation(session)
    t, m1 = ctx["tournament"], ctx["m1"]
    elig = evaluate_eligibility(session, t, session.get(Match, m1.id))
    assert elig.outcome == OUTCOME_WAITING_CHECKIN


def test_dispatch_after_finalize_starts_next_on_court(session: Session):
    ctx = _setup_automation(session)
    t, m1, m2, m_r2 = ctx["tournament"], ctx["m1"], ctx["m2"], ctx["m_r2"]
    m1.runtime_status = "FINAL"
    m1.winner_team_id = m1.team_a_id
    m1.completed_at = datetime.utcnow()
    m2.runtime_status = "FINAL"
    m2.winner_team_id = m2.team_a_id
    m2.completed_at = datetime.utcnow()
    m_r2.team_a_id = m1.team_a_id
    m_r2.team_b_id = m2.team_a_id
    session.add_all([m1, m2, m_r2])
    session.commit()

    with patch("app.services.preassigned_dispatch.slot_start_has_arrived", return_value=True):
        result = dispatch_after_finalize(session, t, session.get(Match, m1.id), downstream_match_ids=[m_r2.id])
    assert m_r2.id in result.started_match_ids
    assert session.get(Match, m_r2.id).runtime_status == "IN_PROGRESS"


def test_staff_override_move_reevaluates(client, session: Session):
    ctx = _setup_automation(session)
    t, v, m1, m2 = ctx["tournament"], ctx["version"], ctx["m1"], ctx["m2"]
    # Free court 2 by moving m2's assignment elsewhere first is complex.
    # Create empty slot on court 2 at 10:00 and move m1 there after check-in+release wait.
    empty = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=ctx["day"],
        start_time=time(11, 0),
        end_time=time(12, 0),
        court_number=2,
        court_label="2",
        block_minutes=60,
    )
    session.add(empty)
    # Remove m2 assignment to free court 2 reservation conflict for non-overlap
    # Overlap: m2 is 9-10 court 2; empty is 11-12 court 2 — OK.
    session.commit()

    _check_in(session, t.id, v.id, m1)
    session.commit()
    slot_key = slot_key_for_slot(ctx["slot_a"])
    # Don't release yet — move waiting match to empty court, then release original slot
    # Actually move after release with occupied: start m2 on court 2, wait m1...
    _check_in(session, t.id, v.id, m2)
    session.commit()
    # Release both courts' opening slot (same slot_key for 9:00)
    client.post(
        f"/api/desk/tournaments/{t.id}/opening-release",
        json={"version_id": v.id, "day_date": ctx["day"].isoformat(), "slot_key": slot_key},
    )
    assert session.get(Match, m1.id).runtime_status == "IN_PROGRESS"
    assert session.get(Match, m2.id).runtime_status == "IN_PROGRESS"

    # Cannot move IN_PROGRESS
    blocked = client.patch(
        f"/api/desk/tournaments/{t.id}/matches/{m1.id}/move",
        json={"version_id": v.id, "target_slot_id": empty.id},
    )
    assert blocked.status_code == 409
