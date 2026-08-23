"""Canonical complete-team rules for RW-OS import snapshots."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional

from app.services.draw_catalog import (
    DRAW_LABELS,
    is_known_draw_label,
    is_waitlist_draw_kind,
    main_draw_kind,
    normalize_draw_label,
    resolve_draw_kind,
)
from app.services.team_rating import (
    classify_rating_status,
    compute_team_rating,
    parse_rating,
)

ACTIVE_REGISTRATION_STATUSES = frozenset({"confirmed", "paid", "invoiced"})
WAITLIST_REGISTRATION_STATUSES = frozenset({"waitlist", "waitlisted", "wait list", "wait-list"})
EXCLUDED_REGISTRATION_STATUSES = frozenset(
    {
        "withdrawn",
        "withdraw",
        "cancelled",
        "canceled",
        "cancel",
        "void",
        "pending",
        "incomplete",
        "failed",
        "declined",
        "decline",
    }
)


def canonicalize_team_key(rw_ids: Iterable[str]) -> str:
    parts = sorted(
        (str(part).strip() for part in rw_ids if str(part).strip()),
        key=lambda value: (int(value) if value.isdigit() else 10**12, value),
    )
    return "/".join(parts)


def normalize_registration_status(raw: Optional[str]) -> str:
    return " ".join((raw or "").strip().lower().replace("_", " ").replace("-", " ").split())


def classify_registration_bucket(status_raw: Optional[str], draw_kind: Optional[str]) -> str:
    status = normalize_registration_status(status_raw)
    compact = status.replace(" ", "")
    if compact in EXCLUDED_REGISTRATION_STATUSES or status in EXCLUDED_REGISTRATION_STATUSES:
        return "excluded"
    if any(token in compact for token in ("void", "cancel", "withdraw", "pending", "incomplete", "failed", "declin")):
        return "excluded"
    if is_waitlist_draw_kind(draw_kind) or compact in {"waitlist", "waitlisted"} or "waitlist" in compact:
        return "waitlist"
    if compact in ACTIVE_REGISTRATION_STATUSES:
        return "active"
    return "excluded"


@dataclass
class SnapshotPlayer:
    rw_id: str
    name: str
    rating: Optional[float]
    rating_field: str = "ntrpRating"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SnapshotTeam:
    team_key: str
    draw_kind: str
    draw_label: str
    player1: SnapshotPlayer
    player2: SnapshotPlayer
    team_rating: Optional[float]
    rating_status: str
    status: str
    bucket: str
    source_record_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "teamKey": self.team_key,
            "drawKind": self.draw_kind,
            "drawLabel": self.draw_label,
            "player1": self.player1.to_dict(),
            "player2": self.player2.to_dict(),
            "teamRating": self.team_rating,
            "ratingStatus": self.rating_status,
            "status": self.status,
            "bucket": self.bucket,
            "sourceRecordKeys": list(self.source_record_keys),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SnapshotTeam":
        p1 = payload.get("player1") or {}
        p2 = payload.get("player2") or {}
        return cls(
            team_key=str(payload.get("teamKey") or payload.get("team_key") or ""),
            draw_kind=str(payload.get("drawKind") or payload.get("draw_kind") or ""),
            draw_label=str(payload.get("drawLabel") or payload.get("draw_label") or ""),
            player1=SnapshotPlayer(
                rw_id=str(p1.get("rw_id") or p1.get("rwId") or ""),
                name=str(p1.get("name") or ""),
                rating=parse_rating(p1.get("rating")),
                rating_field=str(p1.get("rating_field") or p1.get("ratingField") or "ntrpRating"),
            ),
            player2=SnapshotPlayer(
                rw_id=str(p2.get("rw_id") or p2.get("rwId") or ""),
                name=str(p2.get("name") or ""),
                rating=parse_rating(p2.get("rating")),
                rating_field=str(p2.get("rating_field") or p2.get("ratingField") or "ntrpRating"),
            ),
            team_rating=parse_rating(
                payload.get("teamRating") if "teamRating" in payload else payload.get("team_rating")
            ),
            rating_status=str(payload.get("ratingStatus") or payload.get("rating_status") or ""),
            status=str(payload.get("status") or ""),
            bucket=str(payload.get("bucket") or "active"),
            source_record_keys=list(payload.get("sourceRecordKeys") or payload.get("source_record_keys") or []),
        )


@dataclass
class ValidationIssue:
    code: str
    message: str
    team_key: Optional[str] = None
    draw_kind: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sort_teams_for_planning(teams: list[SnapshotTeam]) -> list[SnapshotTeam]:
    return sorted(
        teams,
        key=lambda team: (
            team.team_rating is None,
            -(team.team_rating if team.team_rating is not None else 0.0),
            team.team_key,
        ),
    )


def validate_import_snapshot(
    teams: list[SnapshotTeam],
    waitlist_teams: Optional[list[SnapshotTeam]] = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen_keys: dict[tuple[str, str], SnapshotTeam] = {}
    draw_player_ids: dict[str, dict[str, str]] = {}

    for team in teams:
        if not team.team_key:
            issues.append(
                ValidationIssue("missing_team_key", "Team is missing a stable teamKey.", draw_kind=team.draw_kind)
            )
            continue
        if not is_known_draw_label(team.draw_kind) and not is_known_draw_label(team.draw_label):
            issues.append(
                ValidationIssue("unknown_draw", "Draw is not in the normalized catalog.", team.team_key, team.draw_kind)
            )
        key = (team.draw_kind, team.team_key)
        if key in seen_keys:
            issues.append(
                ValidationIssue(
                    "duplicate_team_key", "Duplicate teamKey in the same draw.", team.team_key, team.draw_kind
                )
            )
        seen_keys[key] = team

        player_ids = [team.player1.rw_id, team.player2.rw_id]
        if not team.player1.rw_id or not team.player2.rw_id:
            issues.append(
                ValidationIssue(
                    "incomplete_partners", "Canonical team requires two RW IDs.", team.team_key, team.draw_kind
                )
            )
        if team.player1.rw_id and team.player2.rw_id:
            expected = canonicalize_team_key(player_ids)
            if expected != team.team_key:
                issues.append(
                    ValidationIssue(
                        "noncanonical_partners",
                        "Partners are not stored as a reciprocal canonical teamKey.",
                        team.team_key,
                        team.draw_kind,
                    )
                )
        draw_seen = draw_player_ids.setdefault(team.draw_kind, {})
        for rw_id in player_ids:
            if not rw_id:
                continue
            prior = draw_seen.get(rw_id)
            if prior and prior != team.team_key:
                issues.append(
                    ValidationIssue(
                        "duplicate_rw_id",
                        f"RW_ID {rw_id} appears on two active teams in the same draw.",
                        team.team_key,
                        team.draw_kind,
                    )
                )
            draw_seen[rw_id] = team.team_key

        for player, label in ((team.player1, "player1"), (team.player2, "player2")):
            if player.rating is None and player.rating_field and str(player.__dict__.get("raw_rating", "")):
                issues.append(
                    ValidationIssue(
                        "invalid_rating", f"{label} rating could not be parsed.", team.team_key, team.draw_kind
                    )
                )

    for team in waitlist_teams or []:
        if (team.draw_kind, team.team_key) in seen_keys:
            issues.append(
                ValidationIssue(
                    "waitlist_mixed_into_active",
                    "Waitlist team is also present in the active draw.",
                    team.team_key,
                    team.draw_kind,
                )
            )

    return issues


def build_snapshot_team(
    *,
    rw_ids: Iterable[str],
    draw_raw: str,
    player_names: dict[str, str],
    player_ratings: dict[str, Any],
    status: str,
    source_record_keys: Optional[list[str]] = None,
) -> Optional[SnapshotTeam]:
    ids = [str(value).strip() for value in rw_ids if str(value).strip()]
    if len(ids) != 2:
        return None
    draw_kind = resolve_draw_kind(draw_raw)
    if not draw_kind:
        return None
    bucket = classify_registration_bucket(status, draw_kind)
    if bucket == "excluded":
        return None
    team_key = canonicalize_team_key(ids)
    p1_id, p2_id = team_key.split("/")
    p1_rating = parse_rating(player_ratings.get(p1_id))
    p2_rating = parse_rating(player_ratings.get(p2_id))
    planning_kind = main_draw_kind(draw_kind) or draw_kind
    return SnapshotTeam(
        team_key=team_key,
        draw_kind=planning_kind if bucket == "active" else draw_kind,
        draw_label=DRAW_LABELS.get(planning_kind if bucket == "active" else draw_kind, normalize_draw_label(draw_raw)),
        player1=SnapshotPlayer(rw_id=p1_id, name=player_names.get(p1_id) or p1_id, rating=p1_rating),
        player2=SnapshotPlayer(rw_id=p2_id, name=player_names.get(p2_id) or p2_id, rating=p2_rating),
        team_rating=compute_team_rating(p1_rating, p2_rating),
        rating_status=classify_rating_status(p1_rating, p2_rating),
        status=status,
        bucket=bucket,
        source_record_keys=list(source_record_keys or []),
    )
