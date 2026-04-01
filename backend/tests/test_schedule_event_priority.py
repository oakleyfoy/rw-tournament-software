import json

from app.models.event import Event
from app.services.schedule_policy_plan import _build_rotated_event_list
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
