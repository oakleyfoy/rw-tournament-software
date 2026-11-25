"""Staff-only notes for tournament players."""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.database import get_session
from app.models.player import Player
from app.models.player_note import PlayerNote
from app.models.tournament import Tournament

router = APIRouter()


class PlayerNoteItem(BaseModel):
    id: int
    player_id: int
    player_name: str
    body: str
    created_at: str
    created_by_name: Optional[str] = None


class PlayerNoteListResponse(BaseModel):
    notes: List[PlayerNoteItem]


class PlayerNoteCreate(BaseModel):
    player_ids: List[int] = Field(min_length=1)
    body: str


def _staff_name(request: Request) -> tuple[Optional[int], Optional[str]]:
    user = getattr(request.state, "current_user", None)
    if user is None:
        return None, None
    name = (getattr(user, "display_name", None) or getattr(user, "username", None) or "").strip() or None
    return getattr(user, "id", None), name


@router.get("/desk/tournaments/{tournament_id}/player-notes", response_model=PlayerNoteListResponse)
def list_player_notes(
    tournament_id: int,
    session: Session = Depends(get_session),
):
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    rows = session.exec(
        select(PlayerNote)
        .where(PlayerNote.tournament_id == tournament_id)
        .order_by(PlayerNote.created_at.desc())  # type: ignore[attr-defined]
    ).all()
    player_ids = {row.player_id for row in rows}
    players = session.exec(select(Player).where(Player.id.in_(list(player_ids)))).all() if player_ids else []  # type: ignore[attr-defined]
    names = {player.id: player.full_name for player in players if player.id is not None}
    return PlayerNoteListResponse(
        notes=[
            PlayerNoteItem(
                id=row.id or 0,
                player_id=row.player_id,
                player_name=names.get(row.player_id) or "Player",
                body=row.body,
                created_at=row.created_at.isoformat(),
                created_by_name=row.created_by_name,
            )
            for row in rows
            if row.id is not None
        ]
    )


@router.post("/desk/tournaments/{tournament_id}/player-notes", response_model=PlayerNoteListResponse)
def create_player_notes(
    tournament_id: int,
    payload: PlayerNoteCreate,
    request: Request,
    session: Session = Depends(get_session),
):
    tournament = session.get(Tournament, tournament_id)
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Note is empty")
    player_ids = list(dict.fromkeys(payload.player_ids))
    players = session.exec(
        select(Player).where(Player.id.in_(player_ids), Player.tournament_id == tournament_id)  # type: ignore[attr-defined]
    ).all()
    found = {player.id for player in players if player.id is not None}
    missing = [player_id for player_id in player_ids if player_id not in found]
    if missing:
        raise HTTPException(status_code=400, detail="Player is not in this tournament")
    user_id, user_name = _staff_name(request)
    now = datetime.now(timezone.utc)
    for player_id in player_ids:
        session.add(
            PlayerNote(
                tournament_id=tournament_id,
                player_id=player_id,
                body=body,
                created_at=now,
                created_by_user_id=user_id,
                created_by_name=user_name,
            )
        )
    session.commit()
    return list_player_notes(tournament_id, session)
