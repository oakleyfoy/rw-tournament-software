"""
Conflict Report Response Models

Phase 3D.3: Wrapper function deleted (Step 3).
This module now only contains Pydantic response models shared across:
- ConflictReportBuilder service
- Route handlers (schedule.py)
- Manual assignment responses

All conflict computation is in ConflictReportBuilder.compute().
"""

from typing import List, Optional

from pydantic import BaseModel


class UnassignedMatchDetail(BaseModel):
    """Details about why a match is unassigned"""
    
    match_id: int
    stage: str
    round_index: int
    sequence_in_round: int
    duration_minutes: int
    reason: str
    notes: Optional[str] = None


class ConflictReportSummary(BaseModel):
    """Top-level summary of schedule state"""
    
    tournament_id: int
    schedule_version_id: int
    total_slots: int
    total_matches: int
    assigned_matches: int
    unassigned_matches: int
    assignment_rate: float


class SlotPressure(BaseModel):
    """Slot availability pressure metrics"""
    
    unused_slots_count: int
    unused_slots_by_day: dict
    unused_slots_by_court: dict
    insufficient_duration_slots_count: int
    longest_match_duration: int
    max_slot_duration: int


class StageTimeline(BaseModel):
    """Timeline information for a stage"""
    
    stage: str
    first_assigned_start_time: Optional[str]
    last_assigned_start_time: Optional[str]
    assigned_count: int
    unassigned_count: int
    spillover_warning: bool


class OrderingViolation(BaseModel):
    """A detected ordering constraint violation"""
    
    type: str
    earlier_match_id: int
    later_match_id: int
    details: str


class OrderingIntegrity(BaseModel):
    """Ordering constraint validation results"""
    
    deterministic_order_ok: bool
    violations: List[OrderingViolation]


class TeamConflictDetail(BaseModel):
    """A detected team overlap conflict (same team in two overlapping slots)"""
    
    match_id: int
    match_code: str
    slot_id: int
    team_id: int
    conflicting_match_id: int
    conflicting_match_code: str
    conflicting_slot_id: int
    details: str


class TeamConflictsSummary(BaseModel):
    """Summary of team overlap conflicts for matches with known teams"""
    
    known_team_conflicts_count: int
    unknown_team_matches_count: int
    conflicts: List[TeamConflictDetail]


class ConflictReportV1(BaseModel):
    """Complete conflict report for a schedule version"""
    
    summary: ConflictReportSummary
    unassigned: List[UnassignedMatchDetail]
    slot_pressure: SlotPressure
    stage_timeline: List[StageTimeline]
    ordering_integrity: OrderingIntegrity
    team_conflicts: Optional[TeamConflictsSummary] = None  # Added for team overlap detection

