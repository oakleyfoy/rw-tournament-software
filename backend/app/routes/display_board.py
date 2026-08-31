"""Staff-only read-only tournament display board API."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.database import get_session
from app.services.display_board import DisplayBoardError, build_display_board, snapshot_to_public_dict

router = APIRouter()


@router.get("/tournaments/{tournament_id}/display-board")
def get_display_board(
    tournament_id: int,
    version_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Canonical live display snapshot for Court Board and Upcoming Matches TVs."""
    try:
        snapshot = build_display_board(session, tournament_id, version_id=version_id)
    except DisplayBoardError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return snapshot_to_public_dict(snapshot)
