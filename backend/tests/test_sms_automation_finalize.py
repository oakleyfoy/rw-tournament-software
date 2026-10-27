"""SMS automation when finalizing matches (post-match next)."""

from datetime import date, time

from sqlmodel import Session

from app.models.event import Event
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.player import Player
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

    teams = [Team(event_id=ev.id, name=f"T{i}", seed=i, display_name=f"T{i}") for i in range(1, 5)]
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


def test_finalize_preview_texts_every_team_number_when_a_player_row_has_no_phone(session: Session):
    t = Tournament(
        name="Four Texts",
        location="Wild Dunes",
        timezone="America/New_York",
        start_date=date(2026, 11, 6),
        end_date=date(2026, 11, 8),
    )
    session.add(t)
    session.flush()
    v = ScheduleVersion(tournament_id=t.id, version_number=1, status="final")
    session.add(v)
    session.flush()
    ev = Event(tournament_id=t.id, category="womens", name="Women's B", team_count=4)
    session.add(ev)
    session.flush()
    donna = Team(
        event_id=ev.id,
        name="Donna Meyer, Atlanta, Georgia / Karen Leff, Atlanta, Georgia (5)",
        display_name="Donna / Karen",
        seed=42,
        player1_cellphone="6785300581",
        player1_email="dmeyer100@att.net",
        player2_cellphone="4046800335",
        player2_email="hanasan@comcast.net",
    )
    traci = Team(
        event_id=ev.id,
        name="Traci Moccia, Point Lookout, NY / peg McDonald, Lido Beach, NY (5)",
        display_name="Traci / peg",
        seed=8,
        player1_cellphone="5162866496",
        player1_email="traci@example.com",
        player2_cellphone="5168843923",
        player2_email="peg@example.com",
    )
    other_a = Team(event_id=ev.id, name="Next A", display_name="Next A", seed=1)
    other_b = Team(event_id=ev.id, name="Next B", display_name="Next B", seed=2)
    session.add_all([donna, traci, other_a, other_b])
    session.flush()
    session.add_all(
        [
            Player(
                tournament_id=t.id,
                full_name="Donna Meyer",
                email="dmeyer100@att.net",
                phone_e164=None,
                sms_consent_status="unknown",
            ),
            Player(
                tournament_id=t.id,
                full_name="Karen Leff",
                display_name="Karen",
                email="hanasan@comcast.net",
                phone_e164="+14046800335",
                sms_consent_status="unknown",
            ),
            Player(
                tournament_id=t.id,
                full_name="Traci Moccia",
                display_name="Traci",
                email="traci@example.com",
                phone_e164="+15162866496",
                sms_consent_status="unknown",
            ),
            Player(
                tournament_id=t.id,
                full_name="peg McDonald",
                display_name="peg",
                email="peg@example.com",
                phone_e164="+15168843923",
                sms_consent_status="unknown",
            ),
        ]
    )
    finished = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 11, 6),
        start_time=time(10, 0),
        end_time=time(11, 0),
        court_number=1,
        court_label="1",
        block_minutes=60,
    )
    donna_next = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 11, 6),
        start_time=time(12, 0),
        end_time=time(13, 0),
        court_number=4,
        court_label="4",
        block_minutes=60,
    )
    traci_next = ScheduleSlot(
        tournament_id=t.id,
        schedule_version_id=v.id,
        day_date=date(2026, 11, 6),
        start_time=time(12, 0),
        end_time=time(13, 0),
        court_number=12,
        court_label="12",
        block_minutes=60,
    )
    session.add_all([finished, donna_next, traci_next])
    session.flush()
    played = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WB_DONE",
        match_type="WF",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=donna.id,
        team_b_id=traci.id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="FINAL",
        winner_team_id=donna.id,
    )
    donna_later = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WB_DONNA_NEXT",
        match_type="WF",
        round_number=2,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=donna.id,
        team_b_id=other_a.id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="SCHEDULED",
    )
    traci_later = Match(
        tournament_id=t.id,
        event_id=ev.id,
        schedule_version_id=v.id,
        match_code="WB_TRACI_NEXT",
        match_type="WF",
        round_number=2,
        round_index=2,
        sequence_in_round=1,
        duration_minutes=60,
        team_a_id=traci.id,
        team_b_id=other_b.id,
        placeholder_side_a="A",
        placeholder_side_b="B",
        runtime_status="SCHEDULED",
    )
    session.add_all([played, donna_later, traci_later])
    session.flush()
    session.add_all(
        [
            MatchAssignment(schedule_version_id=v.id, match_id=played.id, slot_id=finished.id),
            MatchAssignment(schedule_version_id=v.id, match_id=donna_later.id, slot_id=donna_next.id),
            MatchAssignment(schedule_version_id=v.id, match_id=traci_later.id, slot_id=traci_next.id),
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
    session.commit()

    preview = SmsAutomationEngine(session, t, v.id).preview_match_finalized_texts(played)
    intended = {row["intended_phone"] for row in preview["recipients"]}
    assert intended == {"+16785300581", "+14046800335", "+15162866496", "+15168843923"}
    assert preview["total_messages"] == 4
