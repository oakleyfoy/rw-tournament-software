"""SMS automation when finalizing matches (post-match next)."""

from datetime import date, time

from sqlmodel import Session

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.team import Team
from app.models.tournament import Tournament
from app.models.tournament_sms_settings import TournamentSmsSettings
from app.services.sms_automation import SmsAutomationEngine


def test_post_match_next_includes_winner_when_next_slot_is_earlier_same_day(session: Session):
    """
    Winner's next match can be scheduled earlier on the clock than the semifinal
    (e.g. final wave at 11am, semi at 1pm). Post-match SMS must still include the winner.
    """
    t = Tournament(
        name="SMS Next Match Test",
        location="Somewhere",
        timezone="America/Chicago",
        start_date=date(2026, 5, 15),
        end_date=date(2026, 5, 18),
    )
    session.add(t)
    session.flush()

    v = ScheduleVersion(tournament_id=t.id, version_number=1, status="final")
    session.add(v)
    session.flush()

    ev = Event(tournament_id=t.id, category="womens", name="Women's", team_count=8)
    session.add(ev)
    session.flush()

    teams = [
        Team(event_id=ev.id, name=f"T{i}", seed=i, display_name=f"T{i}")
        for i in range(1, 5)
    ]
    session.add_all(teams)
    session.flush()
    ta, tb, tc, td = teams

    slot_early = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 5, 16),
        start_time=time(11, 0),
        end_time=time(12, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    slot_late = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 5, 16),
        start_time=time(13, 0),
        end_time=time(14, 0),
        court_number=13,
        court_label="13",
        block_minutes=60,
    )
    slot_loser = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 5, 17),
        start_time=time(10, 15),
        end_time=time(11, 15),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    session.add_all([slot_early, slot_late, slot_loser])
    session.flush()

    m_semi = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="W_SEMI",
        match_type="WF",
        round_number=2,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=ta.id,
        team_b_id=tb.id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="FINAL",
        winner_team_id=ta.id,
        score_json={"display": "8-1"},
    )
    m_win = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="W_FINAL",
        match_type="WF",
        round_number=3,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=ta.id,
        team_b_id=tc.id,
        placeholder_side_a="A",
        placeholder_side_b="C",
        runtime_status="SCHEDULED",
    )
    m_lose = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="W_LOSE",
        match_type="WF",
        round_number=3,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=tb.id,
        team_b_id=td.id,
        placeholder_side_a="B",
        placeholder_side_b="D",
        runtime_status="SCHEDULED",
    )
    session.add_all([m_semi, m_win, m_lose])
    session.flush()

    session.add_all(
        [
            MatchAssignment(schedule_version_id=v.id, match_id=m_semi.id, slot_id=slot_late.id),
            MatchAssignment(schedule_version_id=v.id, match_id=m_win.id, slot_id=slot_early.id),
            MatchAssignment(schedule_version_id=v.id, match_id=m_lose.id, slot_id=slot_loser.id),
        ]
    )

    session.add(
        TournamentSmsSettings(
            tournament_id=t.id,
            texts_enabled=True,
            auto_checkin_post_match_next=True,
            test_mode=False,
        )
    )
    ta.player1_cellphone = "9015550101"
    tb.player1_cellphone = "9015550102"
    session.add_all([ta, tb])
    session.commit()

    eng = SmsAutomationEngine(session, t, v.id)
    preview = eng.preview_match_finalized_texts(m_semi)
    assert preview["teams_with_next_match"] == 2
    assert preview["total_messages"] >= 2
    phones = {str(r.get("phone") or "") for r in preview["recipients"]}
    assert any("9015550101" in p for p in phones)
    assert any("9015550102" in p for p in phones)
