import { useState, useMemo } from 'react'
import {
  DndContext,
  DragEndEvent,
  DragStartEvent,
  DragOverlay,
  useDraggable,
  useDroppable,
} from '@dnd-kit/core'
import type { ScheduleGridV1, GridSlot, GridMatch, GridAssignment, TeamInfo } from '../../../api/client'
import { timeTo12Hour } from '../../../utils/timeFormat'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface AllDaysGridDnDProps {
  gridData: ScheduleGridV1
  isFinal: boolean
  moving: boolean
  onMove: (assignmentId: number, newSlotId: number) => Promise<void>
  onOccupiedDrop?: (message: string) => void
}

interface DayData {
  dayDate: string
  courts: string[]
  timeRows: { time: string; slotsByCourt: Map<string, GridSlot> }[]
}

// ── Match card (draggable) ────────────────────────────────────────────────────

function MatchCard({
  assignment,
  match,
  teamMap,
  isFinal,
  lockedMatchSet,
  isMoving,
}: {
  assignment: GridAssignment
  match: GridMatch
  teamMap: Map<number, TeamInfo>
  isFinal: boolean
  lockedMatchSet: Set<number>
  isMoving: boolean
}) {
  const isLocked = lockedMatchSet.has(match.match_id)
  const disabled = isFinal || isLocked || isMoving

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `assignment:${assignment.id}`,
    disabled,
  })

  const getTeamLabel = (id: number | null, placeholder: string) => {
    if (id === null) return placeholder
    const t = teamMap.get(id)
    if (!t) return `Team #${id}`
    const label = t.display_name || t.name
    return t.seed ? `#${t.seed} ${label}` : label
  }

  const stageMap: Record<string, string> = {
    WF: 'WF',
    MAIN: 'MN',
    CONSOLATION: 'CN',
    PLACEMENT: 'PL',
    RR: 'RR',
  }

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      style={{
        padding: '6px 8px',
        borderRadius: 4,
        border: isLocked ? '1px solid #ffc107' : '1px solid #90caf9',
        background: isLocked ? '#fff8e1' : '#e3f2fd',
        cursor: disabled ? 'default' : isDragging ? 'grabbing' : 'grab',
        opacity: isDragging ? 0.25 : 1,
        userSelect: 'none',
        fontSize: 12,
        lineHeight: 1.35,
        minHeight: 52,
        touchAction: 'none',
      }}
    >
      {isLocked && (
        <div style={{ fontSize: 9, fontWeight: 700, color: '#f57f17', textTransform: 'uppercase' }}>
          LOCK
        </div>
      )}
      <div style={{ fontWeight: 700, color: '#1565c0', fontSize: 11 }}>
        {stageMap[match.stage] ?? match.stage} R{match.round_index}·{match.sequence_in_round}
      </div>
      <div style={{ color: '#666', fontSize: 10, marginBottom: 2 }}>
        {match.match_code}
      </div>
      <div style={{ color: '#222', fontSize: 11 }}>
        {getTeamLabel(match.team_a_id, match.placeholder_side_a)}
      </div>
      <div style={{ color: '#aaa', fontSize: 10, textAlign: 'center' }}>vs</div>
      <div style={{ color: '#222', fontSize: 11 }}>
        {getTeamLabel(match.team_b_id, match.placeholder_side_b)}
      </div>
    </div>
  )
}

// ── Slot cell (droppable) ─────────────────────────────────────────────────────

function SlotCell({
  slot,
  assignment,
  match,
  teamMap,
  isFinal,
  lockedMatchSet,
  blockedSlotSet,
  isMoving,
}: {
  slot: GridSlot
  assignment: GridAssignment | undefined
  match: GridMatch | undefined
  teamMap: Map<number, TeamInfo>
  isFinal: boolean
  lockedMatchSet: Set<number>
  blockedSlotSet: Set<number>
  isMoving: boolean
}) {
  const isOccupied = !!assignment
  const isBlocked = blockedSlotSet.has(slot.slot_id)

  const { setNodeRef, isOver } = useDroppable({
    id: `slot:${slot.slot_id}`,
    disabled: isFinal || isOccupied || isBlocked,
  })

  let bg = '#fff'
  let border = '1px solid #e0e0e0'
  if (isBlocked) {
    bg = '#fce4e4'
    border = '1px solid #e57373'
  } else if (isOccupied) {
    bg = 'transparent'
    border = 'none'
  } else if (isOver) {
    bg = '#e8f5e9'
    border = '2px dashed #4caf50'
  }

  return (
    <div
      ref={setNodeRef}
      style={{
        padding: 3,
        borderRadius: 4,
        border,
        background: bg,
        minHeight: 58,
        transition: 'background 0.12s, border-color 0.12s',
      }}
    >
      {isBlocked && !isOccupied && (
        <div
          style={{
            fontSize: 9,
            fontWeight: 700,
            color: '#c62828',
            textTransform: 'uppercase',
            padding: '4px 2px',
          }}
        >
          BLOCKED
        </div>
      )}
      {assignment && match ? (
        <MatchCard
          assignment={assignment}
          match={match}
          teamMap={teamMap}
          isFinal={isFinal}
          lockedMatchSet={lockedMatchSet}
          isMoving={isMoving}
        />
      ) : !isBlocked ? (
        <div
          style={{
            color: '#ccc',
            fontSize: 11,
            fontStyle: 'italic',
            padding: '4px 6px',
            lineHeight: 1.3,
          }}
        >
          Open
        </div>
      ) : null}
    </div>
  )
}

// ── Overlay ghost card ────────────────────────────────────────────────────────

function OverlayCard({ match }: { match: GridMatch }) {
  return (
    <div
      style={{
        padding: '8px 12px',
        background: '#1565c0',
        color: '#fff',
        borderRadius: 6,
        boxShadow: '0 6px 24px rgba(0,0,0,0.30)',
        fontSize: 12,
        lineHeight: 1.4,
        minWidth: 140,
        cursor: 'grabbing',
        pointerEvents: 'none',
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: 2 }}>{match.match_code}</div>
      <div style={{ opacity: 0.9 }}>{match.placeholder_side_a}</div>
      <div style={{ opacity: 0.5, fontSize: 10 }}>vs</div>
      <div style={{ opacity: 0.9 }}>{match.placeholder_side_b}</div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function AllDaysGridDnD({
  gridData,
  isFinal,
  moving,
  onMove,
  onOccupiedDrop,
}: AllDaysGridDnDProps) {
  const [draggingAssignmentId, setDraggingAssignmentId] = useState<number | null>(null)

  // Lookup maps
  const assignmentBySlotId = useMemo(() => {
    const m = new Map<number, GridAssignment>()
    gridData.assignments.forEach(a => m.set(a.slot_id, a))
    return m
  }, [gridData.assignments])

  const matchMap = useMemo(() => {
    const m = new Map<number, GridMatch>()
    gridData.matches.forEach(gm => m.set(gm.match_id, gm))
    return m
  }, [gridData.matches])

  const teamMap = useMemo(() => {
    const m = new Map<number, TeamInfo>()
    gridData.teams.forEach(t => m.set(t.id, t))
    return m
  }, [gridData.teams])

  const lockedMatchSet = useMemo(
    () => new Set((gridData.match_locks ?? []).map(ml => ml.match_id)),
    [gridData.match_locks]
  )

  const blockedSlotSet = useMemo(
    () =>
      new Set(
        (gridData.slot_locks ?? [])
          .filter(sl => sl.status === 'BLOCKED')
          .map(sl => sl.slot_id)
      ),
    [gridData.slot_locks]
  )

  // Per-day grid structure
  const dayGridData = useMemo((): DayData[] => {
    const dayGroups = new Map<string, GridSlot[]>()
    gridData.slots.forEach(slot => {
      if (!dayGroups.has(slot.day_date)) dayGroups.set(slot.day_date, [])
      dayGroups.get(slot.day_date)!.push(slot)
    })

    const result: DayData[] = []

    for (const [dayDate, slots] of Array.from(dayGroups.entries()).sort(([a], [b]) =>
      a.localeCompare(b)
    )) {
      const courtSet = new Map<string, number>()
      slots.forEach(s => {
        if (!courtSet.has(s.court_label)) courtSet.set(s.court_label, s.court_id)
      })
      const courts = Array.from(courtSet.entries())
        .sort(([, a], [, b]) => a - b)
        .map(([label]) => label)

      const timeGroups = new Map<string, GridSlot[]>()
      slots.forEach(s => {
        if (!timeGroups.has(s.start_time)) timeGroups.set(s.start_time, [])
        timeGroups.get(s.start_time)!.push(s)
      })

      const timeRows = Array.from(timeGroups.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([time, daySlots]) => {
          const slotsByCourt = new Map<string, GridSlot>()
          daySlots.forEach(s => slotsByCourt.set(s.court_label, s))
          return { time, slotsByCourt }
        })

      result.push({ dayDate, courts, timeRows })
    }

    return result
  }, [gridData.slots])

  // Drag handlers
  const handleDragStart = ({ active }: DragStartEvent) => {
    const id = String(active.id)
    if (id.startsWith('assignment:')) {
      setDraggingAssignmentId(parseInt(id.split(':')[1], 10))
    }
  }

  const handleDragEnd = async ({ active, over }: DragEndEvent) => {
    setDraggingAssignmentId(null)
    if (!over) return

    const activeId = String(active.id)
    const overId = String(over.id)
    if (!activeId.startsWith('assignment:') || !overId.startsWith('slot:')) return

    const assignmentId = parseInt(activeId.split(':')[1], 10)
    const newSlotId = parseInt(overId.split(':')[1], 10)

    const assignment = gridData.assignments.find(a => a.id === assignmentId)
    if (!assignment) return
    if (assignment.slot_id === newSlotId) return

    if (assignmentBySlotId.has(newSlotId)) {
      onOccupiedDrop?.('That slot is already occupied. Remove the existing match first.')
      return
    }

    await onMove(assignmentId, newSlotId)
  }

  const draggingMatch = useMemo(() => {
    if (!draggingAssignmentId) return null
    const a = gridData.assignments.find(a => a.id === draggingAssignmentId)
    return a ? (matchMap.get(a.match_id) ?? null) : null
  }, [draggingAssignmentId, gridData.assignments, matchMap])

  const formatDayLabel = (d: string) =>
    new Date(d + 'T00:00:00').toLocaleDateString('en-US', {
      weekday: 'long',
      month: 'short',
      day: 'numeric',
    })

  return (
    <DndContext onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
      {moving && (
        <div
          style={{
            padding: '8px 16px',
            background: '#fff3e0',
            border: '1px solid #ff9800',
            borderRadius: 4,
            marginBottom: 12,
            fontSize: 13,
            color: '#e65100',
          }}
        >
          Moving match…
        </div>
      )}

      {dayGridData.map(day => (
        <div key={day.dayDate} style={{ marginBottom: 36 }}>
          {/* Day header bar */}
          <div
            style={{
              padding: '10px 16px',
              background: '#1565c0',
              color: '#fff',
              borderRadius: '6px 6px 0 0',
              fontWeight: 700,
              fontSize: 15,
              letterSpacing: 0.3,
            }}
          >
            {formatDayLabel(day.dayDate)}
          </div>

          {/* Scrollable grid table */}
          <div style={{ overflowX: 'auto', border: '1px solid #c5cae9', borderTop: 'none', borderRadius: '0 0 6px 6px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  <th
                    style={{
                      position: 'sticky',
                      left: 0,
                      background: '#e8eaf6',
                      padding: '10px 10px',
                      textAlign: 'left',
                      borderBottom: '2px solid #c5cae9',
                      minWidth: 80,
                      zIndex: 2,
                      fontWeight: 700,
                      color: '#333',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    Time
                  </th>
                  {day.courts.map(court => (
                    <th
                      key={court}
                      style={{
                        padding: '10px 6px',
                        textAlign: 'center',
                        borderBottom: '2px solid #c5cae9',
                        background: '#e8eaf6',
                        minWidth: 150,
                        fontWeight: 700,
                        color: '#333',
                      }}
                    >
                      {court}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {day.timeRows.map(row => (
                  <tr key={row.time} style={{ borderBottom: '1px solid #ede7f6' }}>
                    <td
                      style={{
                        position: 'sticky',
                        left: 0,
                        background: '#fafafa',
                        padding: '6px 10px',
                        fontWeight: 600,
                        whiteSpace: 'nowrap',
                        zIndex: 1,
                        borderRight: '1px solid #e0e0e0',
                        color: '#444',
                        fontSize: 12,
                      }}
                    >
                      {timeTo12Hour(row.time)}
                    </td>
                    {day.courts.map(court => {
                      const slot = row.slotsByCourt.get(court)
                      if (!slot) {
                        return (
                          <td
                            key={court}
                            style={{
                              padding: 4,
                              background: '#f9f9f9',
                              minWidth: 150,
                              color: '#ddd',
                              textAlign: 'center',
                              fontSize: 12,
                            }}
                          >
                            –
                          </td>
                        )
                      }
                      const assignment = assignmentBySlotId.get(slot.slot_id)
                      const match = assignment ? matchMap.get(assignment.match_id) : undefined
                      return (
                        <td key={court} style={{ padding: 4, verticalAlign: 'top' }}>
                          <SlotCell
                            slot={slot}
                            assignment={assignment}
                            match={match}
                            teamMap={teamMap}
                            isFinal={isFinal}
                            lockedMatchSet={lockedMatchSet}
                            blockedSlotSet={blockedSlotSet}
                            isMoving={moving}
                          />
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      <DragOverlay dropAnimation={null}>
        {draggingMatch && <OverlayCard match={draggingMatch} />}
      </DragOverlay>
    </DndContext>
  )
}
