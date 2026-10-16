"""Apply tournament.court_names changes to draft schedule drafts.

When court labels are saved on setup, draft slots must be relabeled in place
so Grid and Check-In pick up the new inventory without a full rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from sqlmodel import Session, select

from app.models.court_state import TournamentCourtState
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.schedule_version import ScheduleVersion
from app.models.slot_lock import SlotLock
from app.models.tournament import Tournament
from app.models.tournament_day import TournamentDay
from app.models.tournament_time_window import TournamentTimeWindow
from app.utils.courts import court_label_for_index, parse_court_names


@dataclass
class CourtSyncStats:
    relabeled_slots: int = 0
    removed_slots: int = 0
    capped_windows: int = 0
    capped_days: int = 0
    remapped_states: int = 0
    removed_states: int = 0

    @property
    def applied(self) -> bool:
        return any(
            (
                self.relabeled_slots,
                self.removed_slots,
                self.capped_windows,
                self.capped_days,
                self.remapped_states,
                self.removed_states,
            )
        )

    def as_dict(self) -> dict:
        return {
            "relabeled_slots": self.relabeled_slots,
            "removed_slots": self.removed_slots,
            "capped_windows": self.capped_windows,
            "capped_days": self.capped_days,
            "remapped_states": self.remapped_states,
            "removed_states": self.removed_states,
        }


def sync_court_names_to_drafts(
    session: Session,
    tournament: Tournament,
    old_names: Optional[Sequence[str]],
    new_names: Optional[Sequence[str]],
) -> CourtSyncStats:
    """
    Align schedule slots with the saved court-name inventory.

    Check-in and the grid read ScheduleSlot.court_label, including on the
    published version. Saving the same list again still repairs labels that
    were stored before this sync existed.

    - Caps active day/window court counts to len(new_names)
    - Relabels every version's slots by court_number index
    - Deletes unassigned slots with court_number > N
    - Remaps TournamentCourtState labels from the slot label change

    Raises ValueError if excess courts still have match assignments.
    No-op when new_names is empty, or when slots already match the list.
    """
    old_parsed = parse_court_names(list(old_names) if old_names is not None else None)
    new_parsed = parse_court_names(list(new_names) if new_names is not None else None)
    stats = CourtSyncStats()

    if not new_parsed:
        return stats

    n = len(new_parsed)
    stats.capped_days = _cap_days(session, tournament.id, n)
    stats.capped_windows = _cap_windows(session, tournament.id, n)

    versions = session.exec(
        select(ScheduleVersion).where(ScheduleVersion.tournament_id == tournament.id)
    ).all()

    label_map: dict[str, str] = {}
    for version in versions:
        relabeled, removed, version_map = _sync_version_slots(session, version.id, new_parsed, n)
        stats.relabeled_slots += relabeled
        stats.removed_slots += removed
        label_map.update(version_map)

    for idx, old_label in enumerate(old_parsed):
        if idx >= n:
            continue
        old_key = (old_label or "").strip()
        if old_key and old_key not in label_map:
            label_map[old_key] = new_parsed[idx]

    remapped, removed_states = _sync_court_states(session, tournament.id, label_map, new_parsed)
    stats.remapped_states += remapped
    stats.removed_states += removed_states

    return stats


def _cap_days(session: Session, tournament_id: int, n: int) -> int:
    capped = 0
    days = session.exec(
        select(TournamentDay).where(
            TournamentDay.tournament_id == tournament_id,
            TournamentDay.is_active == True,  # noqa: E712
        )
    ).all()
    for day in days:
        if day.courts_available > n:
            day.courts_available = n
            session.add(day)
            capped += 1
    return capped


def _cap_windows(session: Session, tournament_id: int, n: int) -> int:
    capped = 0
    windows = session.exec(
        select(TournamentTimeWindow).where(
            TournamentTimeWindow.tournament_id == tournament_id,
            TournamentTimeWindow.is_active == True,  # noqa: E712
        )
    ).all()
    for window in windows:
        avail = int(window.courts_available or 0)
        extra = int(window.extra_courts or 0)
        total = avail + extra
        if total <= n:
            continue
        if avail >= n:
            window.courts_available = n
            window.extra_courts = 0
        else:
            window.extra_courts = n - avail
        session.add(window)
        capped += 1
    return capped


def _sync_version_slots(
    session: Session,
    version_id: int,
    new_names: List[str],
    n: int,
) -> tuple[int, int, dict[str, str]]:
    slots = session.exec(
        select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == version_id)
    ).all()
    if not slots:
        return 0, 0, {}

    keep_slots = [s for s in slots if s.court_number <= n]
    excess_slots = [s for s in slots if s.court_number > n]
    label_map: dict[str, str] = {}

    if excess_slots:
        excess_ids = [s.id for s in excess_slots if s.id is not None]
        if excess_ids:
            assignments = session.exec(
                select(MatchAssignment).where(
                    MatchAssignment.schedule_version_id == version_id,
                    MatchAssignment.slot_id.in_(excess_ids),  # type: ignore[arg-type]
                )
            ).all()
            if assignments:
                courts = sorted({s.court_number for s in excess_slots})
                raise ValueError(
                    f"Cannot shrink court labels: {len(assignments)} match assignment(s) still on "
                    f"court number(s) {courts} beyond the new label count ({n}). "
                    "Move or unassign those matches first."
                )

            locks = session.exec(
                select(SlotLock).where(
                    SlotLock.schedule_version_id == version_id,
                    SlotLock.slot_id.in_(excess_ids),  # type: ignore[arg-type]
                )
            ).all()
            for lock in locks:
                session.delete(lock)

        for slot in excess_slots:
            session.delete(slot)

    relabeled = 0
    for slot in keep_slots:
        new_label = court_label_for_index(new_names, slot.court_number)
        old_label = (slot.court_label or "").strip()
        if old_label and old_label != new_label:
            label_map[old_label] = new_label
        if old_label != new_label:
            slot.court_label = new_label
            session.add(slot)
            relabeled += 1

    return relabeled, len(excess_slots), label_map


def _sync_court_states(
    session: Session,
    tournament_id: int,
    label_map: dict[str, str],
    new_names: List[str],
) -> tuple[int, int]:
    states = session.exec(
        select(TournamentCourtState).where(TournamentCourtState.tournament_id == tournament_id)
    ).all()
    if not states:
        return 0, 0

    new_set = {label for label in new_names}
    remapped = 0
    removed = 0

    # Two-phase remap avoids unique (tournament_id, court_label) collisions
    # when old and new inventories overlap (e.g. 1-15 → 5-18).
    index_pairs: list[tuple[str, str, int]] = []
    for idx, (old_label, new_label) in enumerate(label_map.items()):
        if (old_label or "").strip() == (new_label or "").strip():
            continue
        index_pairs.append((old_label, new_label, idx))

    if index_pairs:
        by_label = {(s.court_label or "").strip(): s for s in states}
        temp_owned: list[tuple[TournamentCourtState, str]] = []
        for old_label, new_label, idx in index_pairs:
            state = by_label.get((old_label or "").strip())
            if not state:
                continue
            temp = f"__sync_tmp_{idx}__"
            state.court_label = temp
            session.add(state)
            temp_owned.append((state, new_label))
            remapped += 1
        session.flush()
        for state, new_label in temp_owned:
            state.court_label = new_label
            session.add(state)
        session.flush()

    # Refresh after remaps
    states = session.exec(
        select(TournamentCourtState).where(TournamentCourtState.tournament_id == tournament_id)
    ).all()
    for state in states:
        label = (state.court_label or "").strip()
        if label and label not in new_set:
            session.delete(state)
            removed += 1

    return remapped, removed
