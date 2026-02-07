"""
Plan Report Endpoints — Schedule readiness validation.

Two endpoints:
  1. GET /tournaments/{tournament_id}/schedule/plan-report
     Draw-plan-only validation (no version required).

  2. GET /tournaments/{tournament_id}/schedule/versions/{version_id}/plan-report
     Full validation including match inventory comparison.
"""

import logging

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.services.plan_report import SchedulePlanReport, build_schedule_plan_report

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/tournaments/{tournament_id}/schedule/plan-report",
    response_model=SchedulePlanReport,
    tags=["plan-report"],
)
def get_plan_report(
    tournament_id: int,
    session: Session = Depends(get_session),
) -> SchedulePlanReport:
    """
    Draw-plan-only validation report.

    Validates that all finalized events have correct draw plans and
    computes expected match counts. Does NOT compare against actual
    match inventory (no version required).

    Use this on the Draw Builder page to gate "Go to Schedule".
    """
    return build_schedule_plan_report(session, tournament_id)


@router.get(
    "/tournaments/{tournament_id}/schedule/versions/{version_id}/plan-report",
    response_model=SchedulePlanReport,
    tags=["plan-report"],
)
def get_plan_report_versioned(
    tournament_id: int,
    version_id: int,
    session: Session = Depends(get_session),
) -> SchedulePlanReport:
    """
    Full validation report with match inventory comparison.

    Validates draw plans AND compares expected vs actual match counts
    for the given schedule version. Also checks placeholder wiring,
    top-2-last-round constraints, and bracket validity.

    Use this on the Schedule Builder page for detailed diagnostics.
    """
    return build_schedule_plan_report(session, tournament_id, version_id)
