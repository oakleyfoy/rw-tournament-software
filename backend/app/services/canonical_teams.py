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


EMPTY_PLACEHOLDERS = frozenset({"", "—", "-", "–", "n/a", "na", "none", "unassigned"})


def present_optional_text(raw: Any) -> Optional[str]:
    value = str(raw or "").strip()
    if not value or value.lower() in EMPTY_PLACEHOLDERS:
        return None
    return value


def normalize_avoid_group(raw: Any) -> Optional[str]:
    value = present_optional_text(raw)
    if not value:
        return None
    parts = [part.strip().upper() for part in value.split(",") if part.strip()]
    return ",".join(parts) if parts else None


def resolve_identity_status(rw_id: str, explicit: Any = None) -> str:
    if explicit in {"rw_id", "unresolved", "secondary"}:
        return str(explicit)
    return "rw_id" if rw_id.strip() else "unresolved"


def _optional_int(raw: Any) -> Optional[int]:
    value = present_optional_text(raw)
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None


@dataclass
class SnapshotPlayer:
    rw_id: str
    name: str
    rating: Optional[float]
    rating_field: str = "ntrpRating"
    city: Optional[str] = None
    state: Optional[str] = None
    cellphone: Optional[str] = None
    email: Optional[str] = None
    towel_color: Optional[str] = None
    identity_status: str = "unresolved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rwId": self.rw_id,
            "rw_id": self.rw_id,
            "name": self.name,
            "city": self.city,
            "state": self.state,
            "cellphone": self.cellphone,
            "email": self.email,
            "towelColor": self.towel_color,
            "towel_color": self.towel_color,
            "rating": self.rating,
            "ratingField": self.rating_field,
            "rating_field": self.rating_field,
            "identityStatus": self.identity_status,
            "identity_status": self.identity_status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SnapshotPlayer":
        rw_id = str(payload.get("rw_id") or payload.get("rwId") or "")
        return cls(
            rw_id=rw_id,
            name=str(payload.get("name") or ""),
            rating=parse_rating(payload.get("rating")),
            rating_field=str(payload.get("rating_field") or payload.get("ratingField") or "ntrpRating"),
            city=present_optional_text(payload.get("city")),
            state=present_optional_text(payload.get("state")),
            cellphone=present_optional_text(payload.get("cellphone")),
            email=present_optional_text(payload.get("email")),
            towel_color=present_optional_text(payload.get("towelColor") or payload.get("towel_color")),
            identity_status=resolve_identity_status(
                rw_id, payload.get("identityStatus") or payload.get("identity_status")
            ),
        )


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
    seed: Optional[int] = None
    avoid_group: Optional[str] = None
    display_name: Optional[str] = None
    full_name: Optional[str] = None
    level: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "teamKey": self.team_key,
            "seed": self.seed,
            "avoidGroup": self.avoid_group,
            "avoid_group": self.avoid_group,
            "displayName": self.display_name,
            "display_name": self.display_name,
            "fullName": self.full_name,
            "full_name": self.full_name,
            "drawKind": self.draw_kind,
            "drawLabel": self.draw_label,
            "level": self.level,
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
            player1=SnapshotPlayer.from_dict(p1 if isinstance(p1, dict) else {}),
            player2=SnapshotPlayer.from_dict(p2 if isinstance(p2, dict) else {}),
            team_rating=parse_rating(
                payload.get("teamRating") if "teamRating" in payload else payload.get("team_rating")
            ),
            rating_status=str(payload.get("ratingStatus") or payload.get("rating_status") or ""),
            status=str(payload.get("status") or ""),
            bucket=str(payload.get("bucket") or "active"),
            source_record_keys=list(payload.get("sourceRecordKeys") or payload.get("source_record_keys") or []),
            seed=_optional_int(payload.get("seed")),
            avoid_group=normalize_avoid_group(payload.get("avoidGroup") or payload.get("avoid_group")),
            display_name=present_optional_text(payload.get("displayName") or payload.get("display_name")),
            full_name=present_optional_text(payload.get("fullName") or payload.get("full_name")),
            level=parse_rating(payload.get("level")),
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
            issues.append(
                ValidationIssue("duplicate_team", "Duplicate team in the same draw.", team.team_key, team.draw_kind)
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

        if not present_optional_text(team.player1.cellphone):
            issues.append(
                ValidationIssue(
                    "missing_player1_cellphone",
                    "Player 1 cellphone is missing.",
                    team.team_key,
                    team.draw_kind,
                )
            )
        if not present_optional_text(team.player1.email):
            issues.append(
                ValidationIssue(
                    "missing_player1_email",
                    "Player 1 email is missing.",
                    team.team_key,
                    team.draw_kind,
                )
            )
        if not present_optional_text(team.player2.cellphone):
            issues.append(
                ValidationIssue(
                    "missing_player2_cellphone",
                    "Player 2 cellphone is missing.",
                    team.team_key,
                    team.draw_kind,
                )
            )
        if not present_optional_text(team.player2.email):
            issues.append(
                ValidationIssue(
                    "missing_player2_email",
                    "Player 2 email is missing.",
                    team.team_key,
                    team.draw_kind,
                )
            )
        if not present_optional_text(team.player1.towel_color) or not present_optional_text(team.player2.towel_color):
            issues.append(
                ValidationIssue(
                    "missing_towel_color",
                    "One or both players are missing a towel color.",
                    team.team_key,
                    team.draw_kind,
                )
            )
        if not present_optional_text(team.avoid_group):
            issues.append(
                ValidationIssue(
                    "missing_who_knows_who",
                    "Who knows who / avoid group is missing.",
                    team.team_key,
                    team.draw_kind,
                )
            )
        if (
            not team.player1.rw_id
            or not team.player2.rw_id
            or team.player1.identity_status == "unresolved"
            or team.player2.identity_status == "unresolved"
        ):
            issues.append(
                ValidationIssue(
                    "unresolved_player_identity",
                    "One or both players are missing a stable RW_ID.",
                    team.team_key,
                    team.draw_kind,
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
