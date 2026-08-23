"""Staging fixtures for RW-OS event import. Never talks to production."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from app.services.canonical_teams import SnapshotPlayer, SnapshotTeam, canonicalize_team_key
from app.services.draw_catalog import DRAW_LABELS
from app.services.team_rating import classify_rating_status, compute_team_rating

TODAY = date(2026, 8, 23)


def _player_name(rw_id: int, prefix: str) -> str:
    families = (
        "Smith",
        "Jones",
        "Brown",
        "Davis",
        "Miller",
        "Wilson",
        "Moore",
        "Taylor",
        "Anderson",
        "Thomas",
        "Jackson",
        "White",
        "Harris",
        "Martin",
        "Thompson",
        "Garcia",
        "Martinez",
        "Robinson",
        "Clark",
        "Rodriguez",
    )
    given = ("Alex", "Blair", "Casey", "Drew", "Eden", "Finley", "Gray", "Harper", "Indigo", "Jules")
    return f"{given[rw_id % len(given)]} {prefix}{families[rw_id % len(families)]}"


def _build_team(
    *,
    p1_id: int,
    p2_id: int,
    p1_rating: Optional[float],
    p2_rating: Optional[float],
    draw_kind: str,
    status: str,
    bucket: str,
) -> SnapshotTeam:
    team_key = canonicalize_team_key([str(p1_id), str(p2_id)])
    left, right = [int(part) for part in team_key.split("/")]
    ratings = {p1_id: p1_rating, p2_id: p2_rating}
    names = {
        p1_id: _player_name(p1_id, "A"),
        p2_id: _player_name(p2_id, "B"),
    }
    return SnapshotTeam(
        team_key=team_key,
        draw_kind=draw_kind,
        draw_label=DRAW_LABELS[draw_kind],
        player1=SnapshotPlayer(rw_id=str(left), name=names[left], rating=ratings[left]),
        player2=SnapshotPlayer(rw_id=str(right), name=names[right], rating=ratings[right]),
        team_rating=compute_team_rating(ratings[left], ratings[right]),
        rating_status=classify_rating_status(ratings[left], ratings[right]),
        status=status,
        bucket=bucket,
        source_record_keys=[f"reg-{team_key}"],
    )


def _linear_pair_ratings(count: int, high: float, low: float, gaps: dict[int, float]) -> list[tuple[float, float]]:
    """Build complete pair ratings whose sums descend, with extra gaps after 1-based ranks."""
    sums: list[float] = []
    current = high
    for rank in range(1, count + 1):
        sums.append(round(current, 4))
        step = (high - low) / max(1, count - 1)
        current -= step
        if rank in gaps:
            current -= gaps[rank]
    pairs = []
    for total in sums:
        half = round(total / 2, 4)
        other = round(total - half, 4)
        pairs.append((half, other))
    return pairs


def _womens_44() -> list[SnapshotTeam]:
    # Strong natural break after rank 20: last A ~4.38+4.38, first B ~4.10+4.10.
    pairs = _linear_pair_ratings(44, 9.84, 6.50, {20: 0.56})
    teams = []
    for index, (p1, p2) in enumerate(pairs, start=1):
        teams.append(
            _build_team(
                p1_id=10000 + index,
                p2_id=20000 + index,
                p1_rating=p1,
                p2_rating=p2,
                draw_kind="womens",
                status="Confirmed",
                bucket="active",
            )
        )
    return teams


def _womens_80() -> list[SnapshotTeam]:
    # Strong natural breaks after ranks 20 and 48 so 20/28/32 can beat 32/28/20.
    pairs = _linear_pair_ratings(80, 10.20, 6.10, {20: 0.55, 48: 0.45})
    teams = []
    for index, (p1, p2) in enumerate(pairs, start=1):
        teams.append(
            _build_team(
                p1_id=30000 + index,
                p2_id=40000 + index,
                p1_rating=p1,
                p2_rating=p2,
                draw_kind="womens",
                status="Paid" if index % 7 == 0 else "Confirmed",
                bucket="active",
            )
        )
    return teams


def _womens_78() -> list[SnapshotTeam]:
    pairs = _linear_pair_ratings(78, 9.90, 6.20, {32: 0.34, 56: 0.44})
    teams = []
    for index, (p1, p2) in enumerate(pairs, start=1):
        status = "Invoiced" if index % 11 == 0 else "Confirmed"
        teams.append(
            _build_team(
                p1_id=50000 + index,
                p2_id=60000 + index,
                p1_rating=p1,
                p2_rating=p2,
                draw_kind="womens",
                status=status,
                bucket="active",
            )
        )
    return teams


def _mixed_11() -> list[SnapshotTeam]:
    pairs = _linear_pair_ratings(11, 8.40, 6.80, {})
    teams = []
    for index, (p1, p2) in enumerate(pairs, start=1):
        teams.append(
            _build_team(
                p1_id=70000 + index,
                p2_id=80000 + index,
                p1_rating=p1,
                p2_rating=p2,
                draw_kind="mixed",
                status="Confirmed",
                bucket="active",
            )
        )
    return teams


def _waitlist_and_excluded_extras() -> tuple[list[SnapshotTeam], list[SnapshotTeam]]:
    waitlist = [
        _build_team(
            p1_id=90001,
            p2_id=90002,
            p1_rating=3.5,
            p2_rating=3.4,
            draw_kind="womens_waitlist",
            status="WaitList",
            bucket="waitlist",
        ),
        _build_team(
            p1_id=90003,
            p2_id=90004,
            p1_rating=3.2,
            p2_rating=3.1,
            draw_kind="womens",
            status="WaitList",
            bucket="waitlist",
        ),
    ]
    excluded = [
        _build_team(
            p1_id=91001,
            p2_id=91002,
            p1_rating=4.0,
            p2_rating=4.0,
            draw_kind="womens",
            status="Withdrawn",
            bucket="excluded",
        )
    ]
    return waitlist, excluded


def _iso(value: date) -> str:
    return value.isoformat()


def _event(
    tournament_id: int,
    event_name: str,
    event_date: date,
    teams: list[SnapshotTeam],
    waitlist: Optional[list[SnapshotTeam]] = None,
    updated_at: Optional[str] = None,
) -> dict[str, Any]:
    waitlist = waitlist or []
    active = [team for team in teams if team.bucket == "active"]
    draws = []
    for team in active:
        if team.draw_label not in draws:
            draws.append(team.draw_label)
    return {
        "organizationSlug": "rw",
        "tournamentId": tournament_id,
        "eventName": event_name,
        "eventDate": _iso(event_date),
        "venue": "Wild Dunes",
        "teamCount": len(active),
        "draws": draws,
        "updatedAt": updated_at or datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc).isoformat(),
        "version": f"rwos-{tournament_id}-v1",
        "teams": [team.to_dict() for team in active],
        "waitlistTeams": [team.to_dict() for team in waitlist],
    }


WILD_DUNES_TEAMS = _womens_78() + _mixed_11()
WILD_DUNES_WAITLIST, WILD_DUNES_EXCLUDED = _waitlist_and_excluded_extras()

EVENTS: dict[int, dict[str, Any]] = {
    148: _event(148, "2026 Wild Dunes", date(2026, 11, 6), WILD_DUNES_TEAMS, WILD_DUNES_WAITLIST),
    244: _event(244, "44-Team Women's Fixture", date(2026, 10, 10), _womens_44()),
    280: _event(280, "80-Team Women's Fixture", date(2026, 12, 4), _womens_80()),
    101: _event(101, "2024 Historical Classic", date(2024, 5, 1), _mixed_11()),
}


def list_fixture_events(*, include_historical: bool = False, as_of: Optional[date] = None) -> list[dict[str, Any]]:
    as_of = as_of or TODAY
    rows = []
    for event in EVENTS.values():
        event_date = date.fromisoformat(event["eventDate"])
        if not include_historical and event_date < as_of:
            continue
        rows.append(
            {
                "organizationSlug": event["organizationSlug"],
                "tournamentId": event["tournamentId"],
                "eventName": event["eventName"],
                "eventDate": event["eventDate"],
                "teamCount": event["teamCount"],
                "draws": event["draws"],
                "updatedAt": event["updatedAt"],
                "version": event["version"],
            }
        )
    return sorted(rows, key=lambda row: (row["eventDate"], row["tournamentId"]))


def get_fixture_event(tournament_id: int) -> Optional[dict[str, Any]]:
    event = EVENTS.get(int(tournament_id))
    if not event:
        return None
    return dict(event)


def mutate_fixture_for_refresh(event: dict[str, Any]) -> dict[str, Any]:
    """Deterministic refresh delta used by tests: +1 team, -1 withdrawn, one rating change."""
    refreshed = dict(event)
    teams = [dict(team) for team in event["teams"]]
    if teams:
        withdrawn = teams.pop()
        refreshed["withdrawnExample"] = withdrawn
    if teams:
        changed = dict(teams[0])
        changed["teamRating"] = round((changed.get("teamRating") or 0) + 0.05, 4)
        p1 = dict(changed["player1"])
        p1["rating"] = round((p1.get("rating") or 0) + 0.05, 4)
        changed["player1"] = p1
        teams[0] = changed
    extra = _build_team(
        p1_id=99001,
        p2_id=99002,
        p1_rating=3.8,
        p2_rating=3.7,
        draw_kind="womens",
        status="Confirmed",
        bucket="active",
    ).to_dict()
    teams.append(extra)
    refreshed["teams"] = teams
    refreshed["teamCount"] = len(teams)
    refreshed["updatedAt"] = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc).isoformat()
    refreshed["version"] = f"{event.get('version', 'rwos')}-refresh"
    return refreshed
