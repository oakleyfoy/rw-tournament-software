"""Sequence phases for Mixed 10 (1 WF) + Women's 20 (2 WF).

Schedule Entire Tournament uses run_sequence_schedule / build_master_sequence,
not the daily policy-plan waves. RR rounds must follow each event's WF count so
Mixed RR R4/R5 never collapse into Friday team-round 1 via the old fallback
(phase 14/15).
"""

from __future__ import annotations

import json

from app.models.event import Event
from app.models.match import Match
from app.services.schedule_sequence import (
    _build_event_phase_map,
    _event_wf_rounds_for_sequence,
    _phase_for_match,
)


def _event(eid: int, name: str, team_count: int, wf_rounds: int) -> Event:
    return Event(
        id=eid,
        tournament_id=1,
        name=name,
        category="mixed",
        team_count=team_count,
        draw_plan_json=json.dumps({"wf_rounds": wf_rounds, "template_type": "WF_TO_POOLS_DYNAMIC"}),
    )


def _m(mid: int, event_id: int, mtype: str, round_index: int, code: str | None = None) -> Match:
    return Match(
        id=mid,
        tournament_id=1,
        event_id=event_id,
        schedule_version_id=1,
        match_code=code or f"E{event_id}_{mtype}_R{round_index}_{mid}",
        match_type=mtype,
        round_number=round_index,
        round_index=round_index,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="a",
        placeholder_side_b="b",
    )


def test_mixed_1wf_rr1_is_friday_team_round_2():
    mixed = _event(2, "Mixed A", 10, wf_rounds=1)
    matches = [_m(1, 2, "WF", 1, "MIX_WF_R1_01")] + [_m(10 + i, 2, "RR", i) for i in range(1, 6)]
    assert _event_wf_rounds_for_sequence(mixed, matches) == 1
    assert _phase_for_match(matches[0], 1) // 10 == 1  # WF R1 → Friday TR1
    assert _phase_for_match(matches[1], 1) // 10 == 2  # RR R1 → Friday TR2 with Women's WF R2
    assert _phase_for_match(matches[4], 1) // 10 == 5  # RR R4 → not Friday TR1


def test_womens_2wf_rr1_is_saturday_team_round_3():
    womens = _event(1, "Women's A", 20, wf_rounds=2)
    matches = [
        _m(1, 1, "WF", 1, "WOM_WF_R1_01"),
        _m(2, 1, "WF", 2, "WOM_WF_R2_01"),
        _m(3, 1, "RR", 1),
    ]
    assert _event_wf_rounds_for_sequence(womens, matches) == 2
    assert _phase_for_match(matches[0], 2) // 10 == 1
    assert _phase_for_match(matches[1], 2) // 10 == 2
    assert _phase_for_match(matches[2], 2) // 10 == 3


def test_mixed_rr4_and_rr5_do_not_share_friday_tr1_with_wf():
    """Regression: STAGE_ORDER_FALLBACK used to map RR4→phase 14 (Friday TR1)."""
    matches = [_m(1, 2, "WF", 1, "MIX_WF_R1_01")] + [_m(10 + i, 2, "RR", i) for i in range(1, 6)]
    phase_map = _build_event_phase_map(matches, wf_rounds=1)
    friday_tr1_phases = [p for p in phase_map if p // 10 == 1]
    assert friday_tr1_phases == [10]
    assert all(m.match_type == "WF" for _mt, _ri, ms in (phase_map[p] for p in friday_tr1_phases) for m in ms)
    rr4_phase = next(p for p, (_mt, ri, _ms) in phase_map.items() if _mt == "RR" and ri == 4)
    assert rr4_phase // 10 == 5


def test_scottsdale_friday_pool_is_wf_then_mixed_rr_with_womens_r2():
    """Team-rounds 1–2 must be: both WF R1, then Women's WF R2 + Mixed RR R1 only."""
    womens_matches = (
        [_m(100 + i, 1, "WF", 1, f"WOM_WF_R1_{i:02d}") for i in range(1, 11)]
        + [_m(200 + i, 1, "WF", 2, f"WOM_WF_R2_{i:02d}") for i in range(1, 11)]
        + [_m(300 + i, 1, "RR", 1) for i in range(1, 11)]
    )
    mixed_matches = [_m(400 + i, 2, "WF", 1, f"MIX_WF_R1_{i:02d}") for i in range(1, 6)] + [
        _m(500 + r * 10 + s, 2, "RR", r) for r in range(1, 6) for s in range(1, 5)
    ]
    w_map = _build_event_phase_map(womens_matches, wf_rounds=2)
    m_map = _build_event_phase_map(mixed_matches, wf_rounds=1)

    def codes_in_tr(phase_map, tr: int) -> set[str]:
        out: set[str] = set()
        for phase, (_mt, _ri, ms) in phase_map.items():
            if phase // 10 == tr:
                out.update(m.match_code or "" for m in ms)
        return out

    assert all(c.startswith("WOM_WF_R1_") for c in codes_in_tr(w_map, 1))
    assert all(c.startswith("MIX_WF_R1_") for c in codes_in_tr(m_map, 1))
    assert all(c.startswith("WOM_WF_R2_") for c in codes_in_tr(w_map, 2))
    assert codes_in_tr(m_map, 2)  # Mixed RR R1 only
    assert all(
        m.match_type == "RR" and m.round_index == 1
        for phase, (_mt, ri, ms) in m_map.items()
        if phase // 10 == 2
        for m in ms
    )
    # No Mixed RR R4/R5 on Friday TR1
    assert not any(
        m.round_index and m.round_index >= 4 for phase, (_mt, ri, ms) in m_map.items() if phase // 10 == 1 for m in ms
    )
