import json

from app.models.event import Event
from app.services.schedule_policy_plan import _build_rotated_event_list, _event_has_wf
from app.services.schedule_sequence import _rotate_events, _sort_events_for_sequence


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
