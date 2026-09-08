"""Staff-only read-only Draw QR Board data API."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from app.database import get_session
from app.services.draw_qr_board import DrawQrBoardError, build_draw_qr_board, snapshot_to_public_dict

router = APIRouter()


@router.get("/tournaments/{tournament_id}/draw-qr-board")
def get_draw_qr_board(
    tournament_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Normalized public-draw QR targets. No tournament-data writes."""
    try:
        snapshot = build_draw_qr_board(
            session,
            tournament_id,
            request_base_url=str(request.base_url),
        )
    except DrawQrBoardError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return snapshot_to_public_dict(snapshot)
