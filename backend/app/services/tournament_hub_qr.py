"""Staff-facing Tournament Hub QR target (one stable URL per tournament).

Reuses the same public origin resolution as the Draw QR Board. The hub URL is
tournament-scoped only — never player- or team-specific.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlmodel import Session

from app.models.tournament import Tournament
from app.services.draw_qr_board import (
    DrawQrBoardError,
    resolve_public_frontend_origin,
    tournament_filename_slug,
)


@dataclass(frozen=True)
class TournamentHubQrSnapshot:
    tournament_id: int
    tournament_name: str
    filename_slug: str
    public_path: str
    public_url: str
    published: bool


def public_tournament_hub_path(tournament_id: int) -> str:
    return f"/t/{tournament_id}/hub"


def build_tournament_hub_qr(
    session: Session,
    tournament_id: int,
    request_base_url: Optional[str] = None,
) -> TournamentHubQrSnapshot:
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise DrawQrBoardError(404, "Tournament not found")

    origin = resolve_public_frontend_origin(request_base_url)
    path = public_tournament_hub_path(tournament_id)
    return TournamentHubQrSnapshot(
        tournament_id=tournament_id,
        tournament_name=tournament.name,
        filename_slug=tournament_filename_slug(tournament.name, tournament_id),
        public_path=path,
        public_url=f"{origin}{path}",
        published=bool(tournament.public_schedule_version_id),
    )


def hub_snapshot_to_public_dict(snapshot: TournamentHubQrSnapshot) -> Dict[str, Any]:
    return {
        "tournament_id": snapshot.tournament_id,
        "tournament_name": snapshot.tournament_name,
        "filename_slug": snapshot.filename_slug,
        "public_path": snapshot.public_path,
        "public_url": snapshot.public_url,
        "published": snapshot.published,
    }
