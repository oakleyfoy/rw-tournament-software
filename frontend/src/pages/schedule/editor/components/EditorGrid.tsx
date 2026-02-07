import { useMemo } from 'react';
import { GridSlot, GridAssignment, GridMatch, TeamInfo } from '../../../../api/client';
import { DraggableAssignment } from './DraggableAssignment';
import { DroppableSlot } from './DroppableSlot';

interface EditorGridProps {
  slots: GridSlot[];
  assignments: GridAssignment[];
  assignmentsBySlotId: Record<number, GridAssignment>;
  matches: Record<number, GridMatch>;
  teams: TeamInfo[];
  isFinal: boolean;
  isPatchingAssignmentId: number | null;
  onUnassign?: (assignmentId: number) => void;
}

export function EditorGrid({
  slots,
  assignments: _assignments,
  assignmentsBySlotId,
  matches,
  isFinal,
  isPatchingAssignmentId,
  onUnassign,
}: EditorGridProps) {
  // Defensive: ensure props are never undefined
  const safeSlots = slots || [];
  const safeAssignmentsBySlotId = assignmentsBySlotId || {};
  const safeMatches = matches || {};

  // Group slots by day and time
  const gridStructure = useMemo(() => {
    const byDay = new Map<string, GridSlot[]>();
    safeSlots.forEach((slot) => {
      if (!byDay.has(slot.day_date)) {
        byDay.set(slot.day_date, []);
      }
      byDay.get(slot.day_date)!.push(slot);
    });

    // Sort each day's slots by start_time, then court_number
    byDay.forEach((daySlots) => {
      daySlots.sort((a, b) => {
        if (a.start_time !== b.start_time) {
          return a.start_time.localeCompare(b.start_time);
        }
        return a.court_id - b.court_id;
      });
    });

    return byDay;
  }, [safeSlots]);

  // Get unique time slots and courts
  const timeSlots = useMemo(() => {
    const times = new Set<string>();
    safeSlots.forEach((s) => times.add(s.start_time));
    return Array.from(times).sort();
  }, [safeSlots]);

  const courts = useMemo(() => {
    const courtSet = new Map<number, string>();
    safeSlots.forEach((s) => courtSet.set(s.court_id, s.court_label));
    return Array.from(courtSet.entries()).sort((a, b) => a[0] - b[0]);
  }, [safeSlots]);

  // Calculate slot duration (assume 15 minutes based on time slots)
  const slotDurationMinutes = 15;

  // Helper: Check if a time slot is occupied by an ongoing match
  const getMatchForTimeSlot = (day: string, time: string, courtNum: number) => {
    // Find the slot at this exact time
    const slot = safeSlots.find(
      (s) => s.day_date === day && s.start_time === time && s.court_id === courtNum
    );
    if (!slot) return null;

    // Check if this slot has an assignment (match starts here)
    const assignment = safeAssignmentsBySlotId[slot.slot_id];
    if (assignment) {
      const match = safeMatches[assignment.match_id];
      if (match) {
        return { assignment, match, isStartSlot: true, slot };
      }
    }

    // Check if there's a match that started earlier and is still ongoing
    // Find all slots for this court on this day before this time
    const earlierSlots = safeSlots
      .filter(
        (s) =>
          s.day_date === day &&
          s.court_id === courtNum &&
          s.start_time < time
      )
      .sort((a, b) => b.start_time.localeCompare(a.start_time)); // Most recent first

    for (const earlierSlot of earlierSlots) {
      const earlierAssignment = safeAssignmentsBySlotId[earlierSlot.slot_id];
        if (earlierAssignment) {
          const match = safeMatches[earlierAssignment.match_id];
        if (match) {
          // Calculate the end time of the match
          const startTimeMinutes = timeToMinutes(earlierSlot.start_time);
          const endTimeMinutes = startTimeMinutes + match.duration_minutes;
          const currentTimeMinutes = timeToMinutes(time);
          
          // If current time is within the match duration, this slot is occupied
          if (currentTimeMinutes < endTimeMinutes) {
            return { assignment: earlierAssignment, match, isStartSlot: false, slot: earlierSlot };
          }
        }
      }
    }

    return null;
  };

  // Helper: Convert time string (HH:MM:SS) to minutes
  const timeToMinutes = (timeStr: string): number => {
    const [hours, minutes] = timeStr.split(':').map(Number);
    return hours * 60 + minutes;
  };

  // Helper: Calculate rowspan for a match
  const getRowspan = (match: GridMatch): number => {
    return Math.ceil(match.duration_minutes / slotDurationMinutes);
  };

  if (safeSlots.length === 0) {
    return (
      <div className="editor-grid-panel">
        <h2>Schedule Grid</h2>
        <div className="loading">No slots available. Generate slots first.</div>
      </div>
    );
  }

  const days = Array.from(gridStructure.keys()).sort();

  return (
    <div className="editor-grid-panel">
      <h2>Schedule Grid</h2>

      {days.map((day) => (
          <div key={day} style={{ marginBottom: '24px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '8px' }}>{day}</h3>
            <table className="grid-table">
              <thead>
                <tr>
                  <th style={{ width: '100px' }}>Time</th>
                  {courts.map(([courtNum, courtLabel]) => (
                    <th key={courtNum}>{courtLabel}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {timeSlots.map((time) => (
                  <tr key={time}>
                    <td>{time}</td>
                    {courts.map(([courtNum]) => {
                      const matchInfo = getMatchForTimeSlot(day, time, courtNum);

                      // If there's a match but this isn't the start slot, skip rendering
                      // (it will be rendered in the start slot with rowspan)
                      if (matchInfo && !matchInfo.isStartSlot) {
                        return null;
                      }

                      if (!matchInfo) {
                        // No match - find slot for dropping
                        const slot = safeSlots.find(
                          (s) =>
                            s.day_date === day &&
                            s.start_time === time &&
                            s.court_id === courtNum
                        );
                        if (!slot) {
                          return <td key={courtNum} className="grid-cell" />;
                        }
                        return (
                          <td key={courtNum}>
                            <DroppableSlot
                              slotId={slot.slot_id}
                              isOccupied={false}
                              isFinal={isFinal}
                            />
                          </td>
                        );
                      }

                      // This is the starting slot - render match with rowspan
                      const rowspan = getRowspan(matchInfo.match);
                      return (
                        <td key={courtNum} rowSpan={rowspan} style={{ verticalAlign: 'top' }} className="occupied-slot">
                          <DroppableSlot
                            slotId={matchInfo.slot.slot_id}
                            isOccupied={true}
                            isFinal={isFinal}
                          >
                            <DraggableAssignment
                              assignmentId={matchInfo.assignment.id}
                              match={matchInfo.match}
                              isLocked={false} // TODO: Add locked field from backend
                              isFinal={isFinal}
                              isPatchingAssignmentId={isPatchingAssignmentId}
                              onUnassign={onUnassign}
                            />
                          </DroppableSlot>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </div>
  );
}

