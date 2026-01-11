"""
Version Safety Guards and Utilities

Provides reusable guards for enforcing version safety rules:
- Draft-only mutations
- Final-only clones
- Version ownership validation
"""

from fastapi import HTTPException
from sqlmodel import Session

from app.models.schedule_version import ScheduleVersion


def require_draft_version(session: Session, version_id: int, tournament_id: int = None) -> ScheduleVersion:
    """
    Require that a schedule version is draft, otherwise raise 400.

    Args:
        session: Database session
        version_id: Schedule version ID
        tournament_id: Optional tournament ID for additional validation

    Returns:
        ScheduleVersion if draft

    Raises:
        HTTPException 404: Version not found
        HTTPException 400: Version is not draft
    """
    version = session.get(ScheduleVersion, version_id)

    if not version:
        raise HTTPException(status_code=404, detail="Schedule version not found")

    if tournament_id and version.tournament_id != tournament_id:
        raise HTTPException(
            status_code=404, detail=f"Schedule version {version_id} does not belong to tournament {tournament_id}"
        )

    if version.status != "draft":
        raise HTTPException(
            status_code=400,
            detail=f"SCHEDULE_VERSION_NOT_DRAFT: Cannot modify version with status '{version.status}'. Only draft versions can be modified.",
        )

    return version


def require_final_version(session: Session, version_id: int, tournament_id: int = None) -> ScheduleVersion:
    """
    Require that a schedule version is final, otherwise raise 400.

    Args:
        session: Database session
        version_id: Schedule version ID
        tournament_id: Optional tournament ID for additional validation

    Returns:
        ScheduleVersion if final

    Raises:
        HTTPException 404: Version not found
        HTTPException 400: Version is not final
    """
    version = session.get(ScheduleVersion, version_id)

    if not version:
        raise HTTPException(status_code=404, detail="Schedule version not found")

    if tournament_id and version.tournament_id != tournament_id:
        raise HTTPException(
            status_code=404, detail=f"Schedule version {version_id} does not belong to tournament {tournament_id}"
        )

    if version.status != "final":
        raise HTTPException(
            status_code=400,
            detail=f"SOURCE_VERSION_NOT_FINAL: Version {version_id} has status '{version.status}'. Only final versions can be cloned.",
        )

    return version


def get_version_or_404(session: Session, version_id: int, tournament_id: int = None) -> ScheduleVersion:
    """
    Get a schedule version or raise 404.

    Args:
        session: Database session
        version_id: Schedule version ID
        tournament_id: Optional tournament ID for validation

    Returns:
        ScheduleVersion

    Raises:
        HTTPException 404: Version not found or doesn't belong to tournament
    """
    version = session.get(ScheduleVersion, version_id)

    if not version:
        raise HTTPException(status_code=404, detail="Schedule version not found")

    if tournament_id and version.tournament_id != tournament_id:
        raise HTTPException(
            status_code=404, detail=f"Schedule version {version_id} does not belong to tournament {tournament_id}"
        )

    return version
