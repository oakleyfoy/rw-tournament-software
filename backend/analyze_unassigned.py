import sys
sys.path.insert(0, ".")
from sqlmodel import Session, select
from app.database import engine
from app.models.match import Match
from app.models.match_assignment import MatchAssignment
from app.models.schedule_slot import ScheduleSlot
from app.models.event import Event
from collections import defaultdict

with Session(engine) as s:
    all_matches = s.exec(select(Match).where(Match.schedule_version_id == 4)).all()
    assigns = s.exec(select(MatchAssignment).where(MatchAssignment.schedule_version_id == 4)).all()
    assigned_ids = {a.match_id for a in assigns}
    
    unassigned = [m for m in all_matches if m.id not in assigned_ids]
    
    events = {e.id: e.name for e in s.exec(select(Event)).all()}
    
    print(f"Total matches: {len(all_matches)}")
    print(f"Assigned: {len(assigned_ids)}")
    print(f"Unassigned: {len(unassigned)}")
    print()
    
    # Group unassigned by event + match_type + round
    groups = defaultdict(list)
    for m in unassigned:
        key = (events.get(m.event_id, "?"), m.match_type, m.round_index)
        groups[key].append(m.match_code)
    
    print("=== Unassigned matches ===")
    for (event, mtype, rnd), codes in sorted(groups.items()):
        print(f"  {event} | {mtype} | round={rnd} | count={len(codes)}")
        for c in sorted(codes):
            print(f"    {c}")
    
    # Slot availability per day
    slots = s.exec(select(ScheduleSlot).where(ScheduleSlot.schedule_version_id == 4, ScheduleSlot.is_active == True)).all()
    used_slot_ids = {a.slot_id for a in assigns}
    
    day_slots = defaultdict(lambda: {"total": 0, "used": 0})
    for sl in slots:
        day_slots[sl.day_date]["total"] += 1
        if sl.id in used_slot_ids:
            day_slots[sl.day_date]["used"] += 1
    
    print()
    print("=== Slot availability ===")
    for d in sorted(day_slots.keys()):
        info = day_slots[d]
        print(f"  {d}: {info['total']} total, {info['used']} used, {info['total'] - info['used']} available")
