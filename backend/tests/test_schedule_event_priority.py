import json

from app.models.event import Event, EventCategory
from app.services.schedule_policy_plan import (
    _build_event_priority_map,
    _build_rotated_event_list,
    _event_has_wf,
    _interleave_match_lists_round_robin,
)
from app.services.schedule_sequence import _rotate_events, _sort_events_for_sequence
from app.utils.event_schedule_orders import event_ids_for_day


def _event(event_id: int, name: str, team_count: int, schedule_order: int | None = None) -> Event:
    profile = None if schedule_order is None else json.dumps({"schedule_order": schedule_order})
    return Event(
        id=event_id,
        tournament_id=1,
        name=name,
        category="mixed",
        team_count=team_count,
        schedule_profile_json=profile,
    )


def _wf_event(event_id: int, name: str, team_count: int, wf_rounds: int = 2) -> Event:
    return Event(
        id=event_id,
        tournament_id=1,
        name=name,
        category="mixed",
        team_count=team_count,
        draw_plan_json=json.dumps({"wf_rounds": wf_rounds}),
    )


def test_policy_priority_manual_order_overrides_larger_draw_first():
    womens = _event(1, "Womens", 16, schedule_order=1)
    mixed = _event(2, "Mixed", 32, schedule_order=2)
    seniors = _event(3, "Seniors", 24)

    ordered = _build_rotated_event_list([mixed, seniors, womens], day_index=0)

    assert [event.name for event in ordered] == ["Womens", "Mixed", "Seniors"]


def test_policy_priority_rotates_only_unordered_events():
    womens = _event(1, "Womens", 16, schedule_order=1)
    mixed = _event(2, "Mixed", 12)
    seniors = _event(3, "Seniors", 12)
    masters = _event(4, "Masters", 8)

    ordered = _build_rotated_event_list([mixed, seniors, masters, womens], day_index=1)

    assert [event.name for event in ordered] == ["Womens", "Seniors", "Mixed", "Masters"]


def test_sequence_priority_keeps_manual_prefix_fixed_during_rotation():
    womens = _event(1, "Womens", 16, schedule_order=1)
    mixed = _event(2, "Mixed", 12)
    seniors = _event(3, "Seniors", 12)
    masters = _event(4, "Masters", 8)

    sorted_events = _sort_events_for_sequence([masters, seniors, mixed, womens])
    rotated = _rotate_events(sorted_events, rotation=1)

    assert [event.name for event in rotated] == ["Womens", "Seniors", "Mixed", "Masters"]


def test_tournament_day_orders_prefix_per_day_index():
    a = _event(1, "A", 32)
    b = _event(2, "B", 16)
    c = _event(3, "C", 24)
    orders = [[3, 1, 2], [2, 3, 1]]
    d0 = _build_rotated_event_list([a, b, c], 0, orders)
    d1 = _build_rotated_event_list([a, b, c], 1, orders)
    assert [e.id for e in d0] == [3, 1, 2]
    assert [e.id for e in d1] == [2, 3, 1]


def test_tournament_day_orders_unknown_ids_skipped():
    a = _event(1, "A", 32)
    b = _event(2, "B", 16)
    orders = [[99999, 2, 1]]
    ordered = _build_rotated_event_list([a, b], 0, orders)
    assert [e.id for e in ordered] == [2, 1]


def test_wf_events_follow_tournament_day_order():
    e1 = _wf_event(1, "E1", 16)
    e2 = _wf_event(2, "E2", 16)
    orders = [[2, 1]]
    full = _build_rotated_event_list([e1, e2], 0, orders)
    wf_ordered = [e for e in full if _event_has_wf(e)]
    assert [e.id for e in wf_ordered] == [2, 1]


def test_event_ids_for_day_reuses_row_when_matrix_shorter_than_slot_days():
    orders = [[2, 1]]
    assert event_ids_for_day(orders, 0) == [2, 1]
    assert event_ids_for_day(orders, 1) == [2, 1]
    assert event_ids_for_day(orders, 99) == [2, 1]


def test_event_ids_for_day_skips_empty_middle_row():
    orders = [[2, 1], [], [3, 2]]
    assert event_ids_for_day(orders, 1) == [2, 1]
    assert event_ids_for_day(orders, 2) == [3, 2]


def test_event_ids_for_day_forward_fallback_when_only_later_rows_filled():
    """Day 0–N rows empty but Sunday (later row) set → reuse that order for earlier days."""
    orders = [[], [], [10, 5]]
    assert event_ids_for_day(orders, 0) == [10, 5]
    assert event_ids_for_day(orders, 1) == [10, 5]
    assert event_ids_for_day(orders, 2) == [10, 5]


def test_mixed_listed_first_beats_womens_even_when_womens_event_id_lower():
    """Regression: template schedule_order often favors Womens; Draw Builder must win."""
    womens = Event(
        id=5,
        tournament_id=1,
        name="Womens",
        category=EventCategory.mixed,
        team_count=16,
        schedule_profile_json=json.dumps({"schedule_order": 1}),
    )
    mixed = Event(
        id=10,
        tournament_id=1,
        name="Mixed",
        category=EventCategory.mixed,
        team_count=16,
        schedule_profile_json=json.dumps({"schedule_order": 2}),
    )
    orders = [[10, 5], [10, 5]]
    for di in (0, 1):
        pr = _build_event_priority_map([mixed, womens], di, orders)
        assert pr[10] < pr[5]
        assert [e.id for e in _build_rotated_event_list([mixed, womens], di, orders)] == [10, 5]


def test_draw_builder_config_disables_profile_schedule_order_in_legacy_tail():
    """When tournament day_orders exist, leftover events use draw-size rotation, not Women's-first profile defaults."""
    womens = _event(1, "Womens", 16, schedule_order=1)
    mixed = _event(2, "Mixed", 32, schedule_order=2)
    orders = [[99999]]
    ordered = _build_rotated_event_list([mixed, womens], 0, orders)
    assert [e.id for e in ordered] == [2, 1]


def test_interleave_match_lists_round_robin_alternates_events():
    """Day 2+ policy merges RR + MAIN tiers without exhausting event A before B."""
    from app.models.match import Match

    rr_mixed_a = Match(
        id=101,
        tournament_id=1,
        event_id=2,
        schedule_version_id=1,
        match_code="MX_RR_01",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=60,
        placeholder_side_a="a",
        placeholder_side_b="b",
    )
    rr_mixed_b = Match(
        id=102,
        tournament_id=1,
        event_id=2,
        schedule_version_id=1,
        match_code="MX_RR_02",
        match_type="RR",
        round_number=1,
        round_index=1,
        sequence_in_round=2,
        duration_minutes=60,
        placeholder_side_a="a",
        placeholder_side_b="b",
    )
    main_womens = Match(
        id=201,
        tournament_id=1,
        event_id=1,
        schedule_version_id=1,
        match_code="W_MAIN_01",
        match_type="MAIN",
        round_number=1,
        round_index=1,
        sequence_in_round=1,
        duration_minutes=90,
        placeholder_side_a="a",
        placeholder_side_b="b",
    )
    merged = _interleave_match_lists_round_robin([[rr_mixed_a, rr_mixed_b], [main_womens]])
    assert [m.id for m in merged[:3]] == [101, 201, 102]
